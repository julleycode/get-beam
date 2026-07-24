---
name: plan:owned-data-layer-docker-verification-note
description: "Backlog: Docker/live-environment verification gaps for owned-data-layer — Hybrid persistence tests + migration apply, never run this session (Docker unavailable)"
date: 23-07-26
metadata:
  node_type: memory
  type: plan
  feature: visitors-identity
  phase: owned-data-layer
---

# Owned Data Layer — Docker/Live-Verification Gap Backlog

**STATUS: RESOLVED (24-07-26).** All gates below closed by an independent EVL final run on a
disposable `infra-postgres-1` container: migration round-trip clean (`upgrade head` →
`downgrade -1` → `upgrade head`, chain to head `a9f2c1e7b4d6`), `test_company_graph.py` 14/14
(double-run), integration `company_graph`+`identity_signals` 5/5, unit regression
`test_agent_origin_exclusion.py` 18/18, donor `test_company_resolver.py` 59/59. 3 test-infra
fixes landed in commit `8c7ac6e`. The two Agent-Probe rows (SendGrid live payload shape;
account-level tracking-settings override) remain genuinely open — not closeable without a live
SendGrid account/payload, carried forward to
`process/features/visitors-identity/backlog/post-docker-gate-followups_NOTE_24-07-26.md`.
`owned-data-layer_PLAN_23-07-26.md` promoted to VERIFIED and archived to `completed/`. This note
is kept as audit trail — do not delete.

**Why this note exists (original, 23-07-26):** per the vacuous-green ban, an acceptance criterion whose only proving
gate is a Docker-gated integration test (or a live migration apply) that has never actually run is
scored **unmet** at closeout, even when unit/regression coverage is fully green. This tracks the
exact residuals for `owned-data-layer_PLAN_23-07-26.md` and the close command for each. None of
these are design defects — every one is "no responsive Docker daemon in this sandbox," a
documented environment gap, not a behavioral gap. Same posture as the EvalLayer program's
equivalent note (`process/features/evallayer/backlog/program-docker-verification-gaps_NOTE_23-07-26.md`).

**Not blocking:** these gaps do not block the plan from being code-complete. They block the plan's
own `## Phase Completion Rules` promotion from CODE DONE to VERIFIED, and its task folder from
moving from `active/` to `completed/`.

## Migration chain (verified via revision headers, 23-07-26 — confirm still current before applying)

```
d11b39a6c843 (agent_visits) → a1c7e4f92b83 (company-resolution fields / is_agent_derived) →
b3f9a1d2c7e5 (ai_referral) → c4e8f1a9d2b7 (agent_fetch_events, Handoff Phase H1) →
f8a2c1d9b3e7 (company_graph, this plan Phase 1) → a3e9f1c7d2b5 (identity_signals, this plan Phase 2 — current head)
```

Re-run `cd apps/api && ../../.venv/bin/alembic heads` before applying — other work may have
advanced the head since this note was written. (Note: `alembic`'s shebang in this checkout
currently points at a stale absolute interpreter path — `alembic heads`/`history` fail with
`No such file or directory` in this sandbox; this is a pre-existing environment issue, not
introduced by this plan. Fix or use `python -m alembic` with an explicit interpreter when running
for real.)

## Close sequence (run once against a live/disposable Postgres + Redis)

```bash
docker compose -f infra/docker-compose.yml up -d postgres redis

cd apps/api
../../.venv/bin/python -m alembic upgrade head
../../.venv/bin/python -m alembic downgrade -1
../../.venv/bin/python -m alembic upgrade head
cd ../..

.venv/bin/python -m pytest tests/integration/test_company_graph_persistence.py -q
.venv/bin/python -m pytest tests/integration/test_identity_signals_persistence.py -q
.venv/bin/python -m pytest tests/ -m integration -q   # full integration lane, confirms no regression
```

## Per-gap inventory

| Gap | AC affected | Proving tier | Close command |
|---|---|---|---|
| `company_graph` real-Postgres upsert/conflict-update never run | AC1 (durability half), AC2b | Hybrid | `pytest tests/integration/test_company_graph_persistence.py -q` |
| `identity_signals` real-Postgres PII pattern (no plaintext email) never run | AC3 (durability half) | Hybrid | `pytest tests/integration/test_identity_signals_persistence.py -q` |
| Both new migrations (`f8a2c1d9b3e7`, `a3e9f1c7d2b5`) never applied/downgraded against a real Postgres | AC8 | Hybrid | `alembic upgrade head && downgrade -1 && upgrade head` (disposable container only — never live/production Postgres) |
| SendGrid live open/click payload shape + `custom_args` echo shape unverified | AC4b (partial) | Agent-Probe | invoke `vc-docs-seeker` for SendGrid's current Event Webhook JSON schema, OR live sandbox replay — cheapest unresolved option per the plan's Known Gap section (option B) |
| Account-level SendGrid tracking-settings override vs explicit payload `tracking_settings` | — | Agent-Probe (needs-live-provider) | manual live-account check, post migration-live-apply — explicitly not probed per VALIDATE cost-class policy; deferred to the operator action of flipping `identity_signals_enabled=True` |

## What is already fully proven (no Docker dependency, do not re-run for "verification")

AC2 (`company_graph_enabled=False` flag-off no-op), AC3's shape-return half (`_graph_node_by_email`
full-profile unit test), AC4's write-gate rejection logic (datacenter/proxy/suppressed/
do_not_resolve — all mocked), AC5 (corroborating-only invariant, both unit-tested and structurally
grep-verified — zero `IdentifiedVisitor` write-path import in `identity_signals.py`), AC6
(suppression regression), AC7 (agent-exclusion boundary regression, 18 passed) are all green today
via the full `tests/unit -q` run (875 passed, 2 skipped) — see
`owned-data-layer_REPORT_23-07-26.md`.

## Next action

Not scheduled — requires a disposable Postgres+Redis instance not available in the current
sandbox. When infra becomes available: run the close sequence above in one sitting, confirm both
Hybrid persistence tests pass and the migration round-trip is clean, then re-enter UPDATE PROCESS
to promote `owned-data-layer_PLAN_23-07-26.md` to VERIFIED and move its task folder from `active/`
to `completed/`.

**Do not flip `company_graph_enabled` or `identity_signals_enabled` to `True` as part of closing
this gap** — that remains a separate, explicit, human, post-migration-live-apply operator action
per the plan's hard safety constraints.
