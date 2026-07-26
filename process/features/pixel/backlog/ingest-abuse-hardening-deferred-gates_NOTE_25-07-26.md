---
name: note:ingest-abuse-hardening-deferred-gates
description: "2 known-gaps left open by ingest-abuse-hardening (pixel) closeout: migration live round-trip, AC-4a mutation-kill re-verification"
date: 25-07-26
feature: pixel
---

# Ingest Abuse Hardening — Deferred Gates

Source: `process/features/pixel/completed/ingest-abuse-hardening_25-07-26/` (archived 26-07-26).
Both gaps are Known-Gaps recorded at EVL closeout, not regressions — code is EVL-PASS
(24 unit + 16 integration, 0 failures, 0 EVL fix cycles). Referenced follow-ups:
`task_8c4771ce` (pre-existing `.url` fixture bug, unrelated, already spawned separately —
do not re-file) and the outstanding `vc-risk-evidence-pack` (plan self-classified high-risk,
never produced).

## Gap 1 — Migration live round-trip not run

`c7d3b8e1f624_add_ingest_abuse_flag.py` was never round-tripped
(`upgrade head` → `downgrade -1` → `upgrade head`) on a disposable Postgres container.

- **Why blocked:** the Docker daemon was down in the EXECUTE environment (`docker info`
  fails). The local Postgres on `:5432` is a shared dev/test server — the plan's binding
  constraint explicitly forbids applying migrations there, so no workaround was used.
- **What WAS done:** offline `--sql` validation both directions —
  `alembic upgrade a9f2c1e7b4d6:c7d3b8e1f624 --sql` and the matching `downgrade --sql` —
  both ran clean.
- **Chain position (re-verified live 26-07-26 via `alembic heads`):** single head,
  `d5b1f7c3a908`. Full chain from `c7d3b8e1f624`: `a9f2c1e7b4d6 → c7d3b8e1f624
  (this migration) → b7d3e9f1a4c2 (ad_connections) → c8e4f2a6b1d9 (ad_audience_links)
  → d5b1f7c3a908 (site_last_aggregated_at, current head)`. No branching — the two
  concurrently-landed `ads` migrations chained cleanly on top.
- **To close:** get a disposable Postgres container (or any environment where the
  Docker daemon is up and NOT the shared dev/test server), run the round-trip against
  the current head, confirm `events.is_flagged_abuse` / `ix_events_site_flagged` /
  `visitors.is_abuse_flagged` / `identified_visitors.is_abuse_flagged` appear and vanish
  cleanly in both directions. Re-run `alembic heads` immediately before applying —
  other concurrent work may have advanced the chain further since 26-07-26.
- **Do NOT enable in any real environment** until this round-trip closes AND the
  migration is actually applied there — matches the `agent_detection_enabled` /
  `company_graph_enabled` precedent (all new flags below default OFF/permissive).

## Gap 2 — AC-4a mutation-kill claim not empirically re-run at closeout

`test_flagged_events_excluded_from_aggregator_rollup` (proves flagged events are excluded
from the `visitor_aggregator.py` rollup) was mutation-tested DURING EXECUTE: the `AND NOT
is_flagged_abuse` FILTER clause was temporarily reverted and the test was observed to fail,
then restored and observed to pass. This is a real, executed mutation test — but at EVL/
UPDATE-PROCESS closeout time the non-vacuousness claim was re-confirmed by **source
inspection only** (reading the diff and the report), not by empirically re-reverting the
filter and re-running the test a second time independently.

- **Risk:** low — the original mutation test was genuinely run and documented with a clear
  before/after result in `ingest-abuse-hardening_REPORT_25-07-26.md` (see "Non-vacuousness
  check on the CRITICAL edit"). This gap is about closeout-time re-verification rigor, not
  about doubting the original result.
- **To close:** re-run the mutation once more independently — temporarily remove `AND NOT
  is_flagged_abuse` from one aggregate FILTER in `apps/api/services/visitor_aggregator.py`,
  confirm `test_flagged_events_excluded_from_aggregator_rollup` fails, then restore and
  confirm it passes again. Takes under 5 minutes; do this before this gate is ever treated
  as "proven" for a higher-risk downstream decision (e.g. before flipping
  `ingest_velocity_enabled` or `site_ingest_limit_enabled` to True in production).

## Related follow-ups (not new work items — reference only)

- `task_8c4771ce` — pre-existing `.url` fixture bug in
  `tests/unit/test_agent_company_resolution.py` (`AttributeError` at
  `apps/api/tasks/resolution_tasks.py:61`), confirmed pre-existing on a stashed clean tree.
  Already spawned as its own task; do not re-file here.
- `vc-risk-evidence-pack` was never produced even though the plan self-classified this work
  as high-risk (auth/schema-adjacent: new DB columns, new emailability guard parameter,
  new rate-limiting surface). Consider producing it retroactively before any of the new
  flags are flipped in production, or before the next phase of ingest hardening begins.
