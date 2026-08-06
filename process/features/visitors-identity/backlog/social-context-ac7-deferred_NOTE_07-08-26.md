---
name: note:social-context-ac7-deferred
description: "AC-7 Hybrid gate deferred (Docker down) — two named SQL-semantics residuals in get_enrich_usage remain unexecuted against real Postgres"
date: 07-08-26
feature: visitors-identity
---

# AC-7 deferred — `get_enrich_usage()` real-Postgres gate not run

**TL;DR** — The Hybrid tier gate for `social-context-merge_07-08-26` could not run: the Docker
daemon was down, so no PostgreSQL was available. The **test file exists and is runnable** —
`tests/integration/test_usage_limits.py`, created by that plan's checklist step 7. Two specific
SQL-semantics residuals remain unproven against a real database.

## To close this gate

```bash
docker compose -f infra/docker-compose.yml up -d postgres redis
.venv/bin/python3.11 -m pytest tests/integration/test_usage_limits.py -q
```

Landing file: `tests/integration/test_usage_limits.py`
Primary test: `TestEnrichUsageMeter::test_enrich_usage_ignores_social_intelligence_only_write`

## Residual (a) — NULL exclusion under SQL three-valued logic

`apps/api/services/usage_limits.py:106-111` filters on exactly two predicates:
`EnrichmentProfile.site_id == site_id` AND `EnrichmentProfile.social_context_updated_at >= today`.

A row whose `social_context_updated_at` is `NULL` **must be EXCLUDED**, because `NULL >= today`
evaluates to `NULL` (not `TRUE`) and `WHERE NULL` does not match. This is correct in principle
and is exactly the case the AC-7 test seeds — but it has **never been executed against real
Postgres**. It is the mechanism by which the BUG-2 fix (deleting the timestamp write) actually
translates into "no quota slot consumed".

## Residual (b) — naive `_today_start()` vs `timestamptz` column

`apps/api/services/usage_limits.py:34-39` `_today_start()` returns a **NAIVE** datetime
(`tzinfo=None`) and carries an inline comment at `usage_limits.py:35-36` asserting
"DB columns are TIMESTAMP WITHOUT TIME ZONE".

**That comment is FALSE for this column.** `apps/api/models/enrichment.py:60` declares
`social_context_updated_at` as `DateTime(timezone=True)` — i.e. `timestamptz` — and baseline
migration `cd811a8b1f32:79` agrees. So `usage_limits.py:110` compares a naive Python datetime
against a tz-aware column; Postgres resolves this via an implicit cast using the session
`TimeZone`. Almost certainly fine in practice (project timezone is UTC), but it is a real
pre-existing mismatch that AC-7 would exercise.

`tests/integration/test_usage_limits.py::test_enrich_usage_excludes_yesterdays_stamp` is the
probe for this residual (day-boundary behaviour).

**Both residuals are PRE-EXISTING and OUT OF SCOPE** of `social-context-merge_07-08-26` —
`usage_limits.py` is READ ONLY per that plan's Touchpoints and not one line of it changed. The
plan relies on these semantics; it does not modify them.

## Why the logic-level inference is still sound

AC-6 (Fully-Automated, green) proves `store_social_context` never writes
`social_context_updated_at`. The counting predicate is read-only and unchanged, and there is no
third variable. So a social-intelligence-only write cannot increment the count. AC-7 upgrades
that inference from airtight-in-logic to observed-in-Postgres.

## Consequence for plan status

`social-context-merge_07-08-26` may be promoted to **CODE DONE** but **NOT** `VERIFIED` until
this gate has actually run and passed.

## Source

`process/features/visitors-identity/active/social-context-merge_07-08-26/social-context-merge_PLAN_07-08-26.md`
— AC-7, Backlog Follow-Up #3, execute-agent instruction E7.
