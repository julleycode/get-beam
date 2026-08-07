---
name: note:job-change-detection-deferred-gates
description: "Two unexecuted gates blocking job-change-detection v1 archival — integration lane (Docker down) and AC-9 dashboard (plan blast-radius contradiction)"
date: 07-08-26
metadata:
  node_type: memory
  type: report
  feature: visitors-identity
---

# Job-Change Detection v1 — Deferred Gates

Source plan: `process/features/visitors-identity/active/job-change-detection_07-08-26/job-change-detection_PLAN_07-08-26.md`
EXECUTE report: same folder, `job-change-detection_REPORT_07-08-26.md`

Backend is code-complete, flag-OFF, 1093/1093 unit tests green. These two gates never ran, so
the plan is **not archivable** (vacuous-green ban: AC-9 has no green proving gate).

## Gap #5 — Integration lane unexecuted (env-blocked)

`tests/integration/test_job_change_detection.py` — 15 tests covering AC-1, AC-2, AC-3, AC-4,
AC-7, AC-8, AC-10, AC-11, AC-12. **Written and collecting cleanly; never executed.**

Blocker: Docker daemon unavailable in the implementing environment — `docker` absent from PATH,
`open -a Docker` did not bring the daemon up in ~12 min, `/usr/local/bin/docker` then vanished.
Postgres 5433 closed throughout.

To close:
```
docker compose -f infra/docker-compose.yml up -d postgres redis
.venv/bin/python3.11 -m pytest tests/integration/test_job_change_detection.py -m integration -q
```

~~Also still open from the plan's own Known-Gap #1: the migration **live round-trip**~~ —
**RESOLVED 07-08-26:** full 64-revision chain (including `a4f2b8c15d70`) applied from an
EMPTY disposable postgres:16-alpine through head `d1a6c4e93f27`; 17-revision downgrade to
`e6b2d4a1c837` + re-upgrade clean. (The integration lane for THIS plan is a separate matter:
`test_job_change_detection.py` ran 07-08-26 and produced 15/15 ERRORS on a fixture bug —
`Visitor` inserted without NOT NULL `first_seen`/`last_seen`. See
`docker-gate-run-findings_NOTE_07-08-26.md`.)

Classification: `harness-drift` (environment), NOT product breakage.

## Gap #6 — AC-9 has no dashboard UI to test (needs a scope decision)

The plan is internally contradictory on AC-9:
- Blast Radius says *"Packages: `apps/api` only. No `apps/web`, no `apps/pixel`"* and lists zero
  `apps/web` touchpoints.
- The validate-contract assigns AC-9 a Hybrid Playwright gate
  (`apps/web/e2e/job-change-dashboard.spec.ts`) marked gap-resolution **B** — "fixed in this plan".

No dashboard component was built, because doing so would be a hard-stop-class expansion past the
declared blast radius. The **API half of AC-9 is delivered and covered**:
`GET /api/v1/sites/{site_id}/job-changes` — site-scoped via `verify_site_access`, ordered newest
first, PII-free response (asserted in
`test_job_changes_endpoint_is_site_scoped`, which also asserts no `email` key leaks).

Two valid resolutions — orchestrator/user picks one:
1. **Descope** the AC-9 Playwright row to the API gate already delivered, and record the UI as
   explicitly out of scope for v1 (consistent with the plan's own blast radius).
2. **Follow-up plan** for the `apps/web` job-change dashboard surface, carrying AC-9's Playwright
   row and its paired Agent-Probe UX row forward.

Recommendation: (1). The plan's blast radius is the more considered of the two statements — it was
written with the shared-surface conflict analysis — and a dashboard surface is a genuinely separate
piece of work with its own UX judgment.

## Not gaps (recorded so they are not re-litigated)

- Known-Gap #2 (confidence table uncalibrated) and #3 (`company_graph` sparse coverage) are
  accepted design tradeoffs documented inline in `services/job_change_detector.py`, not test gaps.
- Known-Gap #4 (`identity_status` vocabulary in flux) was re-verified live at EXECUTE:
  `"anonymous"` is still the current value.
