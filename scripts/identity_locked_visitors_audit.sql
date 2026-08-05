-- Visitors held by the 30-day retry lock that may have been locked by an OUTAGE.
-- READ-ONLY. Every statement is a SELECT. Nothing is written, deleted, flagged,
-- or locked — deliberately.
--
-- Why read-only: `resolution_logs` recorded a provider outage and a genuine
-- "nobody matched" identically (success=False, cost=0.0). That is the bug fixed
-- going forward, but it also means historical rows cannot be told apart with
-- certainty — no failure window was ever recorded. Deleting or rewriting rows on
-- a guess would destroy the only evidence and could unlock visitors that were
-- legitimately no-match. So: list, hand to a human, decide later.
--
-- Which provider actually did the locking is an OPEN question, not a settled
-- one. `docs/identity-us-current-handoff.md` records `leadpipe logs = 0`, so
-- despite the 403 outage being real, Leadpipe cannot be what wrote the locking
-- rows. Q2 below is what answers it — read it before assuming a culprit.
--
-- Status filter note: the affected visitors are `unresolvable`, NOT `anonymous`.
-- `_resolve_full_waterfall` sets `unresolvable` at the end of every unsuccessful
-- pass (identity_resolver.py), so a visitor that went through the waterfall
-- never stays `anonymous`. Filtering on `anonymous` alone returns zero rows and
-- hides the entire affected population. Both are included below.
--
-- What "locked" means: `was_recently_attempted` refuses to retry a visitor that
-- has any resolution_logs row inside the 30-day window, regardless of why that
-- row exists.  → apps/api/services/identity_resolver.py `was_recently_attempted`
-- NOTE: a second, stronger lock exists — `identity_status = 'unresolvable'`
-- excludes a visitor from the resolution sweep entirely
-- (`apps/api/tasks/resolution_tasks.py` selects `anonymous` only). Clearing the
-- 30-day lock alone does NOT re-queue these visitors. Tracked separately.
--
-- Run with:
--   railway run -s retarget-agent -e production -- \
--     psql "$DATABASE_URL" -f scripts/identity_locked_visitors_audit.sql
--
-- Local (docker-compose, port 5433 — credentials from infra/docker-compose.yml):
--   psql "postgresql://retarget:retarget_dev@localhost:5433/retarget_agent" -f scripts/identity_locked_visitors_audit.sql

\timing on
\pset pager off

-- ---------------------------------------------------------------------------
-- L1. How many unidentified visitors are inside the cooldown window at all?
-- ---------------------------------------------------------------------------
\echo '=== L1. Unidentified visitors currently inside the 30-day retry lock ==='
SELECT
  v.site_id,
  v.identity_status,
  COUNT(DISTINCT v.visitor_id)                                   AS locked_visitors,
  MIN(rl.created_at)                                             AS oldest_locking_attempt,
  MAX(rl.created_at)                                             AS newest_locking_attempt
FROM visitors v
JOIN resolution_logs rl
  ON rl.site_id = v.site_id
 AND rl.visitor_id = v.visitor_id
WHERE v.identity_status IN ('anonymous', 'unresolvable')
  AND rl.created_at > NOW() - INTERVAL '30 days'
GROUP BY v.site_id, v.identity_status
ORDER BY locked_visitors DESC;

-- ---------------------------------------------------------------------------
-- L2. Which providers produced the locking rows, and did any of them ever
--     succeed in the same window? A provider with 0 successes across every
--     visitor is the signature of an outage rather than a real no-match.
-- ---------------------------------------------------------------------------
\echo '=== L2. Locking attempts by provider (0 successes = outage signature) ==='
SELECT
  rl.site_id,
  rl.provider,
  COUNT(*)                                          AS attempts,
  COUNT(*) FILTER (WHERE rl.success)                AS successes,
  ROUND(SUM(rl.cost_usd)::numeric, 4)               AS cost_usd,
  MIN(rl.created_at)                                AS first_attempt,
  MAX(rl.created_at)                                AS last_attempt
FROM resolution_logs rl
WHERE rl.created_at > NOW() - INTERVAL '30 days'
GROUP BY rl.site_id, rl.provider
ORDER BY rl.site_id, successes ASC, attempts DESC;

-- ---------------------------------------------------------------------------
-- L3. The list itself: each locked visitor, what locked it, and when the lock
--     expires. This is the hand-off artifact — no action is taken on it here.
-- ---------------------------------------------------------------------------
\echo '=== L3. Locked visitors (candidate wrongly-locked list) ==='
SELECT
  v.site_id,
  v.visitor_id,
  v.country_code,
  v.identity_status,
  v.last_seen::date                                  AS last_seen,
  STRING_AGG(DISTINCT rl.provider, ',' ORDER BY rl.provider) AS providers_tried,
  COUNT(*)                                           AS attempts,
  COUNT(*) FILTER (WHERE rl.success)                 AS successes,
  MAX(rl.created_at)                                 AS last_attempt,
  (MAX(rl.created_at) + INTERVAL '30 days')::date    AS lock_expires
FROM visitors v
JOIN resolution_logs rl
  ON rl.site_id = v.site_id
 AND rl.visitor_id = v.visitor_id
WHERE v.identity_status IN ('anonymous', 'unresolvable')
  AND rl.created_at > NOW() - INTERVAL '30 days'
GROUP BY v.site_id, v.visitor_id, v.country_code, v.identity_status, v.last_seen
HAVING COUNT(*) FILTER (WHERE rl.success) = 0
ORDER BY v.site_id, last_attempt DESC
LIMIT 500;

-- ---------------------------------------------------------------------------
-- L4. Corroboration from the cost ledger. Going forward, outages are tagged
--     `meta->>'outcome' = 'provider_unavailable'` in api_usage_logs while
--     writing NO resolution_logs row. Rows here WITHOUT a matching
--     resolution_logs row are outages recorded under the new behavior — proof
--     the separation is working. Rows for the same visitor/provider that DO
--     have a resolution_logs sibling predate the fix.
-- ---------------------------------------------------------------------------
\echo '=== L4. Outage rows in the cost ledger (new-behavior verification) ==='
SELECT
  aul.site_id,
  aul.provider,
  aul.meta ->> 'outcome'                             AS outcome,
  COUNT(*)                                           AS outage_rows,
  COUNT(*) FILTER (
    WHERE EXISTS (
      SELECT 1 FROM resolution_logs rl
      WHERE rl.site_id = aul.site_id
        AND rl.visitor_id = aul.visitor_id
        AND rl.provider = aul.provider
        AND rl.created_at BETWEEN aul.created_at - INTERVAL '1 minute'
                              AND aul.created_at + INTERVAL '1 minute'
    )
  )                                                  AS with_resolution_log_sibling,
  ROUND(SUM(aul.cost_usd)::numeric, 4)               AS cost_usd,
  MAX(aul.created_at)                                AS last_seen
FROM api_usage_logs aul
WHERE aul.category = 'identity'
  AND aul.meta ->> 'outcome' = 'provider_unavailable'
  AND aul.created_at > NOW() - INTERVAL '90 days'
GROUP BY aul.site_id, aul.provider, aul.meta ->> 'outcome'
ORDER BY outage_rows DESC;

\echo ''
\echo 'Read-only audit complete. No rows were modified.'
\echo 'L3 is a CANDIDATE list, not a confirmed wrongly-locked list: pre-fix rows'
\echo 'cannot prove outage vs no-match. Decide after the provider is verified live.'
