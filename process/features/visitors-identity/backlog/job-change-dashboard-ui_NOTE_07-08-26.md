---
name: note:job-change-dashboard-ui
description: "Deferred UI leg for job-change-detection AC-9 — dashboard trigger/badge + Playwright spec, descoped from job-change-detection_07-08-26"
date: 07-08-26
metadata:
  node_type: memory
  type: report
  feature: visitors-identity
---

# Job-Change Dashboard UI — Deferred Follow-Up

Source plan: `process/features/visitors-identity/active/job-change-detection_07-08-26/job-change-detection_PLAN_07-08-26.md`
Descope decision: user-approved 07-08-26 (resolves Known-Gap #6 / backlog Gap #6 —
`job-change-detection-deferred-gates_NOTE_07-08-26.md`).

## What the UI leg would be

A job-change badge/filter on the hot-contacts dashboard page in `apps/web` (e.g.
`apps/web/src/app/dashboard/hot-contacts/` or wherever that surface currently lives), consuming
the already-delivered `GET /api/v1/sites/{site_id}/job-changes` endpoint
(`apps/api/routers/hot_contacts.py`) to show a "recently changed jobs" trigger/badge per visitor,
plus a Playwright spec (`apps/web/e2e/job-change-dashboard.spec.ts`) asserting the element is
present/visible for a seeded confirmed event.

## Why deferred

- `job-change-detection_07-08-26`'s own Blast Radius explicitly scoped the plan to `apps/api`
  only ("No `apps/web`, no `apps/pixel`") — building the UI would have been a hard-stop-class
  scope expansion.
- The repo-wide Clerk auth-harness gap blocks Playwright auth legs generally (same blocker noted
  across other active plans, e.g. ads-audiences Phase 1/2 AC7) — a new dashboard Playwright spec
  would hit the same wall.
- The API half of AC-9 is already delivered and tested
  (`tests/integration/test_job_change_detection.py::test_job_changes_endpoint_is_site_scoped`),
  so the detection feature is fully functional; only the visual surface is missing.

## What unblocks it

1. Resolve the repo-wide Clerk auth-harness gap for Playwright (tracked elsewhere — not specific
   to this note).
2. A small follow-up plan: build the dashboard badge/filter component consuming the existing
   `/job-changes` endpoint, plus the Playwright spec once the auth-harness gap is resolved.
3. `job_change_detection_enabled` flag must be flipped ON in at least a staging environment to see
   real data in the UI during development.
