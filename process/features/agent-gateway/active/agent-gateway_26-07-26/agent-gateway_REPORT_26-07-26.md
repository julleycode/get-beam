---
phase: agent-gateway-phase-1-2
date: 2026-07-26
status: COMPLETE_WITH_GAPS
feature: agent-gateway
plan: process/features/agent-gateway/active/agent-gateway_26-07-26/agent-gateway_PLAN_26-07-26.md
---

# Agent Gateway — Phase 1 + Phase 2 EXECUTE report

**TL;DR** — Phase 1 (AgentProfile model + migration + authed CRUD + dashboard editor +
SiteUpdate bug fix) and Phase 2 (public manifest/offers/llms.txt + hand-written JSON-RPC
MCP read server + discovery snippet) are code-complete and green: 64 new unit tests, full
unit lane 676 passed, web build compiles, migration clean offline both directions. One
Docker-gated known-gap (migration live round-trip). Phase 3/4 and every identity/PII file
were NOT touched — verified by git status and grep.

## What Was Done

### Phase 1 — agent-facing data model (AC1–AC5)

- `apps/api/models/agent_profile.py` — `AgentProfile`, one row per site. Real
  `ForeignKey("sites.site_id")` + `unique=True` per E5, with the rationale documented
  in-file and in the migration docstring so a future reader doesn't "correct" it to the
  soft no-FK majority style.
- `apps/api/migrations/versions/a4f7c2e9d31b_add_agent_profile.py` — additive new table
  only. `down_revision = e6b2d4a1c837`, **observed live** via `alembic heads` immediately
  before writing (E2), re-confirmed after: single head, no branching.
- `apps/api/schemas/agent_profile.py` — `AgentProfileUpdate` / `AgentProfileOut` /
  `AgentOffer`. Capabilities are a closed allowlist (unknown value ⇒ 422); offers bounded
  at 100.
- `apps/api/routers/agent_profile.py` — `GET`/`PUT /api/v1/agent-profile/{site_id}`, both
  behind `verify_site_access`. E7 decision: **404 on GET before any PUT** (a read never
  creates a row), upsert on PUT; documented in the module docstring.
- `apps/api/schemas/sites.py` + `apps/api/routers/sites.py` — latent bug fix: `SiteUpdate`
  now accepts and persists `description` / `category`. Additive/optional, so no existing
  caller changes behavior.
- `apps/web/src/lib/api-types.ts` + `api.ts` — `AgentProfile`, `AgentOffer`,
  `AgentCapability`, `AgentProfileUpdate` types plus `getAgentProfile` / `saveAgentProfile`.
- `apps/web/src/app/dashboard/agent/page.tsx` — profile editor.

### Phase 2 — public representation surface (AC6–AC10)

- `apps/api/config.py` — `agent_gateway_enabled: bool = False`, commented in the
  `agent_fetch_beacon_enabled` house style with the two-gate rule and the operator
  rollout precondition.
- `apps/api/schemas/agent_gateway.py` — UCP-compatible manifest shape (reverse-domain
  `fyi.getbeam.agent.*` capability names, service version, endpoints map) and ACP-feed
  offer shape.
- `apps/api/services/agent_gateway.py` — the **single source of truth** for every public
  surface. `resolve_public_profile()` is the only way in and returns `None` for all of:
  global flag off / unknown site / no profile / disabled profile. Builders read only
  customer-authored fields.
- `apps/api/routers/agent_gateway.py` — `GET .../manifest.json`, `/offers.json`,
  `/llms.txt`. Rate-limited, cache header shared verbatim with `llms.txt`/`ai-plugin.json`.
- `apps/api/routers/agent_mcp.py` — hand-written JSON-RPC 2.0 dispatcher, no new
  dependency (E3). All four required guards implemented: rate-limit parity, 16 KB body cap
  checked from both Content-Length and actual bytes *before* parsing, strict 3-method
  allow-list with `-32601` objects, and no raw-input echo (error messages are fixed
  literals; the JSON-RPC `id` is echoed only when a scalar ≤128 chars).
- `apps/api/main.py` — model registered, three routers mounted.
- Discovery snippet (`<link rel="alternate">` + JSON-LD) generated in the dashboard page.
- `posture-reversal_REF_26-07-26.md` — the AC10 reconciliation, in writing.

### Deliberate correctness improvement found during EXECUTE

`AgentProfile` creation in the router now sets `enabled=False, offers=[], capabilities=[]`
**explicitly** rather than relying on SQLAlchemy column defaults. A public-exposure kill
switch should be off by construction, not by flush-time side effect. Surfaced by a test
that caught `enabled=None` on the pre-flush object.

## What Was Skipped or Deferred

- **Phase 3 and Phase 4 — not started, per E8.** No action endpoint, no consent link, no
  `agent_action.py` / `consent_receipt.py`, no `/c/{token}`, no `isPublicRoute` change, no
  `consent_capture.py`.
- MCP action tools deliberately absent; `MCP_TOOLS` holds exactly the 3 read tools, with a
  test asserting no action tool has leaked in.
- Manifest capability `endpoint` fields are `null` — Phase 1+2 publish declarations only.
- JSON-RPC batch requests unsupported by design (they multiply work per rate-limit token).

## Test Gate Outcomes

| Gate | Result |
|---|---|
| `pytest tests/unit/test_agent_profile.py` (new, 13 tests) | **PASS** — 13 passed |
| `pytest tests/unit/test_agent_gateway_public.py` (new, 20 tests) | **PASS** — 20 passed |
| `pytest tests/unit/test_agent_mcp.py` (new, 31 tests) | **PASS** — 31 passed |
| `pytest tests/unit/test_agent_origin_exclusion.py tests/unit/test_outbound_identity_gate.py` | **PASS** — 36 passed, files untouched |
| Full unit lane `pytest tests/unit -m unit` | **PASS** — 676 passed, 2 skipped |
| `cd apps/web && npm run build` | **PASS** — compiled; `/dashboard/agent` 4.61 kB |
| Migration offline `--sql` upgrade `e6b2d4a1c837:a4f7c2e9d31b` | **PASS** — clean CREATE TABLE + index |
| Migration offline `--sql` downgrade `a4f7c2e9d31b:e6b2d4a1c837` | **PASS** — clean DROP INDEX + DROP TABLE |
| `alembic heads` after write | **PASS** — `a4f7c2e9d31b`, single head |
| Migration **live round-trip** on disposable Postgres | **KNOWN-GAP** — Docker daemon down |
| AC5 grep: every Phase 1 route ownership-checked | **PASS** — asserted in test, plus a route-introspection test proving every `/api/v1/agent-profile` route depends on `get_current_user` |
| AC10 posture-reversal note | **PASS** — written (see deviation below) |
| E8 scope grep (Phase 3/4 + identity files) | **PASS** — zero hits, zero git changes |
| 5 core regression validators | **3 PASS / 3 pre-existing failures unrelated to this work** |

Validator detail: `validate-agent-parity`, `validate-plan-inventory`, `git diff --check`
pass. `validate-skills` and `validate-kit-portability` fail on
`.claude/skills/yc-application-coach/**` (untracked, from a different session);
`validate-context-discovery` fails on `.claude/worktrees/*/…/communication-standards.md`.
None name an agent-gateway file. Not introduced by this pass.

## Plan Deviations

1. **AC10 note location.** The Phase 2 checklist asks for a dated cross-reference appended
   to `process/features/evallayer/.../phase-00-discoverability_PLAN_22-07-26.md`. The
   EXECUTE handoff explicitly forbids touching `process/features/evallayer/**`. The
   reconciliation was therefore written to
   `agent-gateway_26-07-26/posture-reversal_REF_26-07-26.md` instead. Substance delivered,
   location differs. Follow-up noted in that file for UPDATE PROCESS.
2. **Explicit defaults on profile creation** (see above) — a small hardening beyond the
   literal checklist, inside the phase's blast radius, in the direction of the plan's own
   default-OFF safety constraint.
3. `ai-plugin.json` was **not** edited, so the evallayer Phase-0 grep constraint still
   holds as written — nothing to reconcile in code, only in prose.

## Test Infra Gaps Found

- Unit tests that construct ORM objects must `import apps.api.main` first (known repo
  gotcha) **and** hand-populate `server_default` columns (`created_at`, `updated_at`,
  `enabled`), which a real flush would set. A shared `_stamp()`-style helper in
  `tests/conftest.py` would remove this per-file boilerplate.
- No disposable-Postgres helper exists for migration round-trips; each phase re-derives
  the docker-compose incantation by hand.

## Closeout Packet

- **Selected plan:** `process/features/agent-gateway/active/agent-gateway_26-07-26/agent-gateway_PLAN_26-07-26.md`
- **Finished:** Phase 1 and Phase 2 implementation checklists in full.
- **Verified:** all Fully-Automated gates green (64 new tests + 676-test unit lane + web
  build + migration offline both directions).
- **Still unverified:** migration live round-trip (Docker); `curl` cache-header check
  against a running local API (Hybrid); dashboard manual save smoke (Agent-Probe).
- **Classification:** `Keep in active/testing` — code-complete, but Phase 1's Exit Gate
  requires the migration round-trip evidence (or its documented known-gap acceptance), and
  Phase 3/4 remain unstarted in the same plan file.
- **Next valid state:** run EVL, then either accept the Docker known-gap per the program's
  established precedent and proceed to a fresh VALIDATE pass for Phase 3, or bring Docker
  up and close the round-trip gate first.

## Follow-up stubs created

None as separate plan files. Two residuals recorded here:
1. Migration live round-trip for `a4f7c2e9d31b` (Docker-gated).
2. Evallayer Phase-0 pointer to the posture-reversal note (UPDATE PROCESS task).

## CONTEXT_PARTIAL items

None. All required context files were readable.

## Forward Preview

**Test Infra Found** — In-process ASGI testing via `ASGITransport` with
`app.dependency_overrides[get_db]` and `[get_current_user]` gives real routing, real
status codes, and real rate-limiter wiring with zero DB/Redis. This is now the cheapest
way to test any router in this repo and Phase 3 should reuse it directly (the fake-session
classes in `tests/unit/test_agent_profile.py` are copy-ready).

**Blast Radius Changes** — `apps/api/routers/agent_gateway.py` and
`apps/api/services/agent_gateway.py` are shared with Phase 3 (created here, extended
there). Phase 3 must extend `resolve_public_profile`'s callers rather than adding a second
tenancy path, or the two surfaces will drift on the never-403 rule.

**Commands to Stay Green**
```
.venv/bin/python3.11 -m pytest tests/unit/test_agent_profile.py tests/unit/test_agent_gateway_public.py tests/unit/test_agent_mcp.py -q
.venv/bin/python3.11 -m pytest tests/unit/test_agent_origin_exclusion.py tests/unit/test_outbound_identity_gate.py -q
cd apps/web && npm run build
```
Docker-gated gate to run when the daemon is up:
```
docker compose -f infra/docker-compose.yml up -d postgres
.venv/bin/python3.11 -m alembic -c apps/api/alembic.ini upgrade a4f7c2e9d31b
.venv/bin/python3.11 -m alembic -c apps/api/alembic.ini downgrade e6b2d4a1c837
.venv/bin/python3.11 -m alembic -c apps/api/alembic.ini upgrade a4f7c2e9d31b
```

**Dependency Changes** — None. No package added to `requirements.txt` or `package.json`;
the JSON-RPC dispatcher is hand-written per E3.

**Migration chain** — head moved `e6b2d4a1c837` → `a4f7c2e9d31b`. Phase 3's migration must
re-run `alembic heads` live before writing `down_revision`; do not assume `a4f7c2e9d31b`
is still head by then.
