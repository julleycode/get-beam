-- Identity-resolution audit — Beam's OWN logs, last 90 days.
-- READ-ONLY. Every statement is a SELECT; nothing is written or locked.
--
-- Purpose: answer with production data the questions the code cannot answer by
-- reading it. Before changing what Beam sends to identity providers, establish
-- which providers actually produce a match at all, and where candidates are
-- lost. Guessing at provider input while Leadpipe/Capturify may be returning
-- zero matches would optimise a path that never fires.
--
-- Questions this answers (mapped to docs/visitor-identity-flow-architecture.md §6):
--   Q3  → is any paid provider succeeding, and at what cost per identity
--   Q4  → is the free pre-waterfall (owned data) carrying the load
--   Q5  → are first-party signals (fingerprint / svid / captured email) present
--   Q7  → how many eligible visitors never get attempted
--
-- Run with:
--   railway run -s retarget-agent -e production -- \
--     psql "$DATABASE_URL" -f scripts/identity_resolution_audit.sql
--
-- Local (docker-compose, port 5433):
--   psql "postgresql://beam:beam@localhost:5433/beam" -f scripts/identity_resolution_audit.sql

\timing on
\pset pager off

-- ---------------------------------------------------------------------------
-- Q1. Baseline. Everything below is a share of this.
-- ---------------------------------------------------------------------------
\echo '=== Q1. Baseline: visitors per site, 90 days ==='
SELECT
  v.site_id,
  s.url,
  s.auto_identify_enabled,
  s.daily_resolution_budget,
  COUNT(*)                                      AS visitors,
  COUNT(*) FILTER (WHERE v.ip_address IS NOT NULL) AS with_ip,
  MIN(v.first_seen)::date                       AS first_day,
  MAX(v.last_seen)::date                        AS last_day
FROM visitors v
LEFT JOIN sites s ON s.site_id = v.site_id
WHERE v.last_seen >= now() - interval '90 days'
GROUP BY v.site_id, s.url, s.auto_identify_enabled, s.daily_resolution_budget
ORDER BY visitors DESC
LIMIT 20;

-- ---------------------------------------------------------------------------
-- Q2. Where does every visitor end up? The funnel's terminal states.
--     'anonymous' that never appears in resolution_logs = never attempted.
-- ---------------------------------------------------------------------------
\echo ''
\echo '=== Q2. identity_status distribution ==='
SELECT
  identity_status,
  COUNT(*)                                                  AS visitors,
  ROUND(100.0 * COUNT(*) / NULLIF(SUM(COUNT(*)) OVER (), 0), 2) AS pct
FROM visitors
WHERE last_seen >= now() - interval '90 days'
GROUP BY identity_status
ORDER BY visitors DESC;

-- ---------------------------------------------------------------------------
-- Q3. THE CENTRAL QUESTION. Per-provider attempt volume and hit rate.
--     A provider with attempts > 0 and successes = 0 is dead weight — its
--     input needs fixing (or it needs disabling) before anything else.
--     A provider absent from this table entirely was never called: check its
--     *_enabled flag and API key.
-- ---------------------------------------------------------------------------
\echo ''
\echo '=== Q3. Provider attempts vs successes (the decision table) ==='
SELECT
  provider,
  COUNT(*)                                                      AS attempts,
  COUNT(*) FILTER (WHERE success)                               AS successes,
  ROUND(100.0 * COUNT(*) FILTER (WHERE success) / NULLIF(COUNT(*), 0), 2) AS hit_rate_pct,
  ROUND(SUM(cost_usd)::numeric, 4)                              AS total_cost_usd,
  ROUND(
    (SUM(cost_usd) / NULLIF(COUNT(*) FILTER (WHERE success), 0))::numeric, 4
  )                                                             AS cost_per_success,
  ROUND(AVG(response_time_ms)::numeric, 0)                      AS avg_ms,
  ROUND(
    (PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY response_time_ms))::numeric, 0
  )                                                             AS p95_ms
FROM resolution_logs
WHERE created_at >= now() - interval '90 days'
GROUP BY provider
ORDER BY attempts DESC;

-- ---------------------------------------------------------------------------
-- Q3b. Same, but per site — a provider can work on one site's traffic profile
--      and be useless on another (US vs non-US, B2B vs consumer).
-- ---------------------------------------------------------------------------
\echo ''
\echo '=== Q3b. Provider hit rate per site ==='
SELECT
  site_id,
  provider,
  COUNT(*)                                                      AS attempts,
  COUNT(*) FILTER (WHERE success)                               AS successes,
  ROUND(100.0 * COUNT(*) FILTER (WHERE success) / NULLIF(COUNT(*), 0), 2) AS hit_rate_pct
FROM resolution_logs
WHERE created_at >= now() - interval '90 days'
GROUP BY site_id, provider
HAVING COUNT(*) >= 5
ORDER BY site_id, attempts DESC;

-- ---------------------------------------------------------------------------
-- Q4. Owned (free, $0) vs paid. This is the ratio the owned-data program
--     exists to move. Providers listed here mirror OWNED_FREE_PROVIDERS in
--     apps/api/services/identity_classification.py — keep them in sync.
-- ---------------------------------------------------------------------------
\echo ''
\echo '=== Q4. Which provider actually produced each stored identity ==='
SELECT
  COALESCE(resolution_provider, '(null)')       AS provider,
  CASE
    WHEN resolution_provider IN (
      'form_capture','fingerprint_match','beam_identity_network','svid_reconcile'
    ) THEN 'owned_free'
    WHEN resolution_provider IN ('rb2b','leadpipe','capturify') THEN 'paid_graph'
    WHEN resolution_provider IN ('hunter','apollo')             THEN 'company_guess'
    WHEN resolution_provider = 'pdl_person_enrich'              THEN 'paid_enrich'
    ELSE 'other'
  END                                           AS class,
  COUNT(*)                                      AS identities,
  COUNT(*) FILTER (WHERE email IS NOT NULL)     AS with_email,
  COUNT(*) FILTER (WHERE full_name IS NOT NULL) AS with_name,
  ROUND(AVG(confidence_score)::numeric, 3)      AS avg_confidence
FROM identified_visitors
WHERE resolved_at >= now() - interval '90 days'
GROUP BY 1, 2
ORDER BY identities DESC;

-- ---------------------------------------------------------------------------
-- Q5. First-party signal coverage. These three are what the free pre-waterfall
--     runs on. Low coverage here means the paid waterfall carries everything —
--     and it is the cheapest thing to fix (no provider involved).
--     NOTE: fingerprint / server_visitor_id only populate correctly on builds
--     carrying the tracker withCredentials + visitor-stub upsert fixes.
-- ---------------------------------------------------------------------------
\echo ''
\echo '=== Q5. First-party signal coverage per site ==='
SELECT
  v.site_id,
  COUNT(*)                                                     AS visitors,
  COUNT(*) FILTER (WHERE v.fingerprint IS NOT NULL)            AS has_fingerprint,
  ROUND(100.0 * COUNT(*) FILTER (WHERE v.fingerprint IS NOT NULL)
        / NULLIF(COUNT(*), 0), 1)                              AS fp_pct,
  COUNT(*) FILTER (WHERE v.server_visitor_id IS NOT NULL)      AS has_svid,
  ROUND(100.0 * COUNT(*) FILTER (WHERE v.server_visitor_id IS NOT NULL)
        / NULLIF(COUNT(*), 0), 1)                              AS svid_pct,
  COUNT(DISTINCT ve.visitor_id)                                AS has_captured_email
FROM visitors v
LEFT JOIN visitor_emails ve
       ON ve.site_id = v.site_id AND ve.visitor_id = v.visitor_id
WHERE v.last_seen >= now() - interval '90 days'
GROUP BY v.site_id
ORDER BY visitors DESC
LIMIT 20;

-- ---------------------------------------------------------------------------
-- Q5b. Captured-email sources. Tells which capture surface in tracker.js is
--      actually firing (form / mailto / url_param / bid / beamIdentify).
-- ---------------------------------------------------------------------------
\echo ''
\echo '=== Q5b. visitor_emails by source ==='
SELECT
  source,
  COUNT(*)                      AS rows,
  COUNT(DISTINCT visitor_id)    AS distinct_visitors,
  COUNT(DISTINCT site_id)       AS sites
FROM visitor_emails
WHERE created_at >= now() - interval '90 days'
GROUP BY source
ORDER BY rows DESC;

-- ---------------------------------------------------------------------------
-- Q6. Attempt depth. How many providers does a visitor burn before a result?
--     A high provider-count with success=false everywhere means the waterfall
--     runs to exhaustion on every candidate.
-- ---------------------------------------------------------------------------
\echo ''
\echo '=== Q6. Providers tried per visitor, and outcome ==='
WITH per_visitor AS (
  SELECT
    site_id,
    visitor_id,
    COUNT(DISTINCT provider)                  AS providers_tried,
    BOOL_OR(success)                          AS any_success,
    SUM(cost_usd)                             AS spent
  FROM resolution_logs
  WHERE created_at >= now() - interval '90 days'
  GROUP BY site_id, visitor_id
)
SELECT
  providers_tried,
  COUNT(*)                                            AS visitors,
  COUNT(*) FILTER (WHERE any_success)                 AS ended_identified,
  ROUND(SUM(spent)::numeric, 4)                       AS total_spent,
  ROUND(
    (SUM(spent) / NULLIF(COUNT(*) FILTER (WHERE any_success), 0))::numeric, 4
  )                                                   AS spend_per_identity
FROM per_visitor
GROUP BY providers_tried
ORDER BY providers_tried;

-- ---------------------------------------------------------------------------
-- Q7. Eligible-but-never-attempted. The silent loss: visitors that passed the
--     eligibility rule but have no resolution_logs row at all. Large numbers
--     here mean the sweep is budget/throughput-bound, not provider-bound —
--     which would make provider-input tuning the wrong first move.
--     Intent floor 20 = RESOLUTION_MIN_INTENT (apps/api/models/visitor.py).
-- ---------------------------------------------------------------------------
\echo ''
\echo '=== Q7. Eligible visitors never attempted ==='
SELECT
  v.site_id,
  COUNT(*)                                             AS eligible_never_attempted,
  ROUND(AVG(v.intent_score)::numeric, 1)               AS avg_intent,
  COUNT(*) FILTER (WHERE v.ai_source IS NOT NULL)      AS ai_referred
FROM visitors v
WHERE v.last_seen >= now() - interval '90 days'
  AND v.identity_status = 'anonymous'
  AND v.do_not_resolve IS FALSE
  AND v.is_agent_derived IS FALSE
  AND v.ip_address IS NOT NULL
  AND (v.intent_score >= 20 OR v.ai_source IS NOT NULL)
  AND NOT EXISTS (
    SELECT 1 FROM resolution_logs rl
    WHERE rl.site_id = v.site_id AND rl.visitor_id = v.visitor_id
  )
GROUP BY v.site_id
ORDER BY eligible_never_attempted DESC
LIMIT 20;

-- ---------------------------------------------------------------------------
-- Q8. Pre-gate losses. Visitors refused BEFORE any provider was called.
--     'vpn_filtered' rising means privacy-relay/VPN traffic dominates and no
--     amount of provider-input tuning will help those rows.
-- ---------------------------------------------------------------------------
\echo ''
\echo '=== Q8. Pre-provider refusals ==='
SELECT
  identity_status,
  COUNT(*)                                          AS visitors,
  COUNT(*) FILTER (WHERE fingerprint IS NOT NULL)   AS still_have_fingerprint
FROM visitors
WHERE last_seen >= now() - interval '90 days'
  AND identity_status IN ('vpn_filtered', 'unresolvable', 'merged')
GROUP BY identity_status
ORDER BY visitors DESC;

-- ---------------------------------------------------------------------------
-- Q9. Cross-tenant graph size. The owned asset that makes future resolutions
--     free. Growth here is the long-term win condition.
-- ---------------------------------------------------------------------------
\echo ''
\echo '=== Q9. Beam identity graph size ==='
SELECT
  COUNT(*)                                        AS nodes,
  COUNT(DISTINCT fingerprint)                     AS distinct_fingerprints,
  COUNT(*) FILTER (WHERE full_name IS NOT NULL)   AS with_name,
  COUNT(DISTINCT source_site_id)                  AS contributing_sites,
  MIN(created_at)::date                           AS oldest,
  MAX(created_at)::date                           AS newest
FROM beam_identity_graph;

\echo ''
\echo '=== done ==='
