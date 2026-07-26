---
name: note:cadence-bot-flag-deferred-gates
description: "4 known-gaps left open by cadence-bot-flag (pixel) EXECUTE+EVL closeout: migration live round-trip, AC-14 live-crawler validation, AC-8/AC-9 Agent-Probe manual render check, Playwright/Clerk auth-harness leg — plus the apps/web RTL/jsdom test-infra backlog candidate"
date: 26-07-26
feature: pixel
---

# Cadence Bot Flag — Deferred Gates

Source: `process/features/pixel/active/cadence-bot-flag_26-07-26/` (plan STAYS active — not
archived; see UPDATE PROCESS closeout). Code is EVL-PASS (25 unit + 7 integration, 0 failures,
0 EVL fix cycles, mutation-kill proved AC-3's conjunction non-vacuous). All 4 gaps below were
pre-accepted at VALIDATE (CONDITIONAL, execute-eligible) and re-confirmed unresolved at EVL —
none are regressions, none silently dropped.

## Gap 1 — Migration live round-trip not run

`e6b2d4a1c837_add_cadence_bot_flag.py` was never round-tripped (`upgrade head` →
`downgrade -1` → `upgrade head`) on a disposable Postgres container.

- **Why blocked:** no `docker` CLI in the EXECUTE/EVL environment. A local Postgres was
  reachable (integration lane ran against it), but that server is shared dev/test — the plan's
  binding constraint forbids applying new migrations there.
- **What WAS done:** offline `--sql` validation both directions —
  `alembic upgrade d5b1f7c3a908:head --sql` (scoped range; see the rev-range gotcha below) and
  `alembic downgrade -1 --sql` — both ran clean, producing the expected 2×
  `ADD COLUMN ... BOOLEAN NOT NULL DEFAULT false` / 2× `DROP COLUMN` statements.
- **Chain position (re-verified live 26-07-26 via `alembic heads`):** single head,
  `e6b2d4a1c837`. Full chain: `... → d5b1f7c3a908 → e6b2d4a1c837 (add_cadence_bot_flag,
  current head)`. Matches the unbroken precedent — none of the last 5 migrations
  (`c7d3b8e1f624`, `b7d3e9f1a4c2`, `c8e4f2a6b1d9`, `d5b1f7c3a908`, `e6b2d4a1c837`) are
  live-round-tripped.
- **To close:** get a disposable Postgres container, run the round-trip against the current
  head, confirm `visitors.is_bot_suspect` / `identified_visitors.is_bot_suspect` appear and
  vanish cleanly both directions. Re-run `alembic heads` immediately before applying — other
  concurrent work may have advanced the chain further since 26-07-26.
- **Do NOT enable `cadence_bot_flag_enabled` in any real environment** until this round-trip
  closes AND the migration is actually applied there — matches the `agent_detection_enabled` /
  `ingest_velocity_enabled` precedent (new flag defaults OFF).

## Gap 2 — AC-14 live-crawler validation (SPEC-level, Agent-Probe by design)

The detection logic (cadence-variance + engagement-ratio conjunction) is proven only against
synthetic fixtures (AC-1–AC-13). Whether the motivating real stealth-crawler's actual historical
event data trips the flag is untested — requires production data.

- **To close:** run the operator runbook already written inline in the plan
  (`## AC-14 Operator Verification Runbook`, Step 15) — a one-time post-deploy check: apply the
  migration, set `cadence_bot_flag_enabled=true`, run the sweep once against the motivating
  case's real `site_id`/`visitor_id`, compare the verdict to the operator's own out-of-band
  confirmation that the visitor is a bot. Tune `cadence_bot_flag_max_variance_threshold` /
  `cadence_bot_flag_max_engagement_ratio` from the observed signal values — never ship the
  `0.15` / `0.05` defaults blind.

## Gap 3 — AC-8/AC-9 Agent-Probe manual render check not yet performed

The detail-page and list-page bot-suspect badges are implemented (conditional render on
`is_bot_suspect`, distinct `bg-warning-muted`/`text-warning` tone vs. the `ai_source` info pill,
`tsc --noEmit` clean) but no agent has visually loaded the rendered pages against flagged/
unflagged fixtures. `apps/web` has zero React component-render test infrastructure (no
`@testing-library/react`, no jsdom vitest project, zero `.test.tsx` files anywhere in the repo)
— PVL supplement cycle 1 (26-07-26) reclassified this gate from Fully-Automated/Hybrid to
Agent-Probe with written rationale (plan `## Known-Gaps #4`).

- **To close:** a reviewing agent (or human) loads `/dashboard/visitors` and a visitor detail
  page against `is_bot_suspect: true` and `is_bot_suspect: false` data/fixtures and visually
  confirms the badge is present/absent respectively, on both the list row and the detail page.

## Gap 4 — Playwright/Clerk auth-harness leg for AC-8

Full end-to-end detail-page rendering under a real authenticated Clerk session is blocked on the
same repo-wide auth-harness gap noted for prior pixel/ads-audiences UI ACs. Not fixable within
this plan's scope.

- **To close:** tracked as a repo-wide known-gap, not specific to this plan — resolves whenever
  the shared Clerk auth-harness gap is addressed (see `process/context/all-context.md` for other
  programs carrying the same gap).

## Backlog candidate — apps/web component-render test infra (RTL/jsdom)

Not a gap in this plan's own coverage (Agent-Probe is a legitimate, explicitly-named proving
strategy per the vacuous-green ban) — a standing infrastructure debt this plan surfaced but
correctly declined to fix as a side effect (PVL-supplement mode forbids introducing new test
infra as scope creep).

- **What's missing:** `apps/web/vitest.config.ts` is `environment: "node"`,
  `include: ["src/**/*.test.ts"]` only; no `@testing-library/react` / `jsdom` in
  `apps/web/package.json` devDependencies; zero `.test.tsx` files exist anywhere in the repo.
- **Candidate future plan:** add `@testing-library/react` + `jsdom` as new `apps/web`
  devDependencies, add a jsdom-scoped vitest project/config (or a per-file
  `// @vitest-environment jsdom` pragma), extend `vitest.config.ts`'s `include` glob to also
  match `src/**/*.test.tsx`. Would unblock AC-8/AC-9-style component-render checks project-wide,
  not just for this feature. Scope this as its own dedicated plan (general-plans or a
  `dev-tooling`-class feature), not tacked onto a future unrelated feature.

## Operator go-live sequence (once ready to enable)

1. Re-run `alembic -c apps/api/alembic.ini heads` — confirm current head still chains cleanly
   onto `e6b2d4a1c837` (or whatever the live head has since become).
2. Apply the migration chain live (production), including `e6b2d4a1c837_add_cadence_bot_flag.py`.
3. Close Gap 1 (live round-trip) on a disposable Postgres BEFORE the production apply, per the
   unbroken precedent set by every prior migration in this chain.
4. Perform Gap 3 (Agent-Probe manual render check) — confirm badges render correctly.
5. Set `CADENCE_BOT_FLAG_ENABLED=true` (tune thresholds from real event-history samples first —
   never ship `0.15`/`0.05` blind).
6. Wait one `cadence_bot_flag_sweep_interval_minutes` tick (default 60 min).
7. Perform the Gap 2 (AC-14) operator runbook against the motivating real crawler's `site_id`/
   `visitor_id` — confirm `is_bot_suspect` flips true, and spot-check the flagged identity stays
   fully emailable and fully counted in dashboard aggregates (the single most important safety
   re-confirm — this flag is visibility-only by design).

## Related notes (not new work items — reference only)

- Precedent format: `process/features/pixel/backlog/ingest-abuse-hardening-deferred-gates_NOTE_25-07-26.md`
- Pre-existing, unrelated defect found during EXECUTE (not this plan's scope):
  `b7d3e9f1a4c2_add_ad_connections.py` is not offline-`--sql`-safe as part of an unscoped
  `alembic upgrade head --sql` (calls `sa.inspect(bind)`, unsupported against alembic's offline
  `MockConnection`). Any future full-chain offline validation must scope around it
  (`upgrade <from>:<to> --sql`) until that migration is fixed.
