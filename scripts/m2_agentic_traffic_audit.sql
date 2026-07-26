-- M2 — Agentic-traffic audit, Beam's OWN logs, last 90 days.
-- READ-ONLY. Every statement is a SELECT; nothing is written or locked.
--
-- Purpose: measure how much of Beam's real traffic looks agent-driven, instead of
-- trusting a single vendor's published share numbers (HUMAN Security's sample is
-- skewed toward fraud-sensitive customers and toward power users — Comet holding
-- 47.6% of their denominator is itself evidence the denominator is small).
--
-- Signals used, in order of durability (deliberately NOT user-agent product names —
-- Atlas is shut down 9 Aug 2026 and the ChatGPT Chrome extension will look different,
-- so anything keyed to a product string rots within weeks):
--   1. behavioural — zero scroll, near-zero dwell, many pages in a short burst
--   2. context     — Chromium UA + empty referrer + structured multi-step navigation
--
-- Run with:
--   railway run -s retarget-agent -e production -- \
--     psql "$DATABASE_URL" -f scripts/m2_agentic_traffic_audit.sql

\timing on
\pset pager off

-- ---------------------------------------------------------------------------
-- Q1. Baseline volume. Everything below is a share of this.
-- ---------------------------------------------------------------------------
\echo '=== Q1. Baseline: 90-day volume per site ==='
SELECT
  site_id,
  COUNT(*)                                   AS events,
  COUNT(DISTINCT visitor_id)                 AS visitors,
  MIN(created_at)::date                      AS first_day,
  MAX(created_at)::date                      AS last_day
FROM events
WHERE created_at >= now() - interval '90 days'
GROUP BY site_id
ORDER BY events DESC
LIMIT 20;

-- ---------------------------------------------------------------------------
-- Q2. What is actually hitting us? Grouped by UA family, not by product name.
--     A high "chromium_generic" share is expected — agentic browsers masquerade
--     as vanilla Chrome, which is precisely why UA alone cannot classify them.
-- ---------------------------------------------------------------------------
\echo ''
\echo '=== Q2. UA families (90d) ==='
SELECT
  CASE
    WHEN user_agent = '' OR user_agent IS NULL              THEN 'empty'
    WHEN user_agent ~* 'bot|crawler|spider|headless'        THEN 'declared_bot'
    WHEN user_agent ~* 'chatgpt|claude|perplexity|gptbot'   THEN 'declared_ai_agent'
    WHEN user_agent ~* 'chrome/'                            THEN 'chromium_generic'
    WHEN user_agent ~* 'safari/'                            THEN 'safari'
    WHEN user_agent ~* 'firefox/'                           THEN 'firefox'
    ELSE 'other'
  END                                        AS ua_family,
  COUNT(*)                                   AS events,
  COUNT(DISTINCT visitor_id)                 AS visitors,
  ROUND(100.0 * COUNT(*) / NULLIF(SUM(COUNT(*)) OVER (), 0), 2) AS pct_events
FROM events
WHERE created_at >= now() - interval '90 days'
GROUP BY 1
ORDER BY events DESC;

-- ---------------------------------------------------------------------------
-- Q3. Ghost visits — the strongest behavioural tell.
--     A human who genuinely reads a page scrolls and lingers. An agent extracts
--     the DOM and moves on: scroll_depth 0 and dwell under ~2s.
--     This is a RATIO question, not an absolute one — compare the ghost share of
--     Chromium traffic against Safari/Firefox, which have no agentic mode.
--     A materially higher ghost share for Chromium is the signal.
-- ---------------------------------------------------------------------------
\echo ''
\echo '=== Q3. Ghost-visit share by UA family (pageviews only, 90d) ==='
SELECT
  CASE
    WHEN user_agent ~* 'bot|crawler|spider|headless'      THEN 'declared_bot'
    WHEN user_agent ~* 'chatgpt|claude|perplexity|gptbot' THEN 'declared_ai_agent'
    WHEN user_agent ~* 'chrome/'                          THEN 'chromium_generic'
    WHEN user_agent ~* 'safari/'                          THEN 'safari'
    WHEN user_agent ~* 'firefox/'                         THEN 'firefox'
    ELSE 'other'
  END                                                     AS ua_family,
  COUNT(*)                                                AS pageviews,
  SUM(CASE WHEN COALESCE(scroll_depth,0) = 0
            AND COALESCE(time_on_page,0) <= 2 THEN 1 ELSE 0 END) AS ghost_views,
  ROUND(100.0 * SUM(CASE WHEN COALESCE(scroll_depth,0) = 0
                          AND COALESCE(time_on_page,0) <= 2 THEN 1 ELSE 0 END)
        / NULLIF(COUNT(*), 0), 2)                         AS ghost_pct
FROM events
WHERE created_at >= now() - interval '90 days'
  AND event_type = 'pageview'
GROUP BY 1
HAVING COUNT(*) >= 20
ORDER BY pageviews DESC;

-- ---------------------------------------------------------------------------
-- Q4. Burst navigation — many distinct pages in a very short window.
--     Agents fan out across a site to answer one question; humans do not read
--     4+ distinct pages in under 60 seconds. Combined with an empty referrer
--     (agentic browsers frequently strip it) this is the candidate population.
-- ---------------------------------------------------------------------------
\echo ''
\echo '=== Q4. Agentic-profile candidate visitors (90d) ==='
WITH bursts AS (
  SELECT
    site_id,
    visitor_id,
    date_trunc('minute', created_at)            AS bucket,
    COUNT(DISTINCT page_path)                   AS pages,
    MAX(created_at) - MIN(created_at)           AS span,
    BOOL_AND(COALESCE(referrer,'') = '')        AS all_empty_referrer,
    AVG(COALESCE(scroll_depth,0))               AS avg_scroll,
    MAX(user_agent)                             AS ua
  FROM events
  WHERE created_at >= now() - interval '90 days'
    AND event_type = 'pageview'
  GROUP BY 1,2,3
),
flagged AS (
  SELECT * FROM bursts
  WHERE pages >= 4
    AND span <= interval '60 seconds'
    AND avg_scroll = 0
)
SELECT
  site_id,
  COUNT(*)                                      AS burst_windows,
  COUNT(DISTINCT visitor_id)                    AS candidate_visitors,
  SUM(CASE WHEN all_empty_referrer THEN 1 ELSE 0 END) AS with_empty_referrer,
  SUM(CASE WHEN ua ~* 'chrome/' THEN 1 ELSE 0 END)    AS on_chromium
FROM flagged
GROUP BY site_id
ORDER BY candidate_visitors DESC
LIMIT 20;

-- ---------------------------------------------------------------------------
-- Q5. Share of total. The number that decides whether P0-A is worth building:
--     candidate agentic visitors as a percentage of all visitors.
-- ---------------------------------------------------------------------------
\echo ''
\echo '=== Q5. Candidate share of all visitors (90d, all sites) ==='
WITH bursts AS (
  SELECT site_id, visitor_id, date_trunc('minute', created_at) AS bucket,
         COUNT(DISTINCT page_path) AS pages,
         MAX(created_at) - MIN(created_at) AS span,
         AVG(COALESCE(scroll_depth,0)) AS avg_scroll
  FROM events
  WHERE created_at >= now() - interval '90 days' AND event_type = 'pageview'
  GROUP BY 1,2,3
),
cands AS (
  SELECT DISTINCT site_id, visitor_id FROM bursts
  WHERE pages >= 4 AND span <= interval '60 seconds' AND avg_scroll = 0
),
total AS (
  SELECT COUNT(DISTINCT visitor_id) AS all_visitors
  FROM events WHERE created_at >= now() - interval '90 days'
)
SELECT
  (SELECT COUNT(*) FROM cands)                  AS candidate_visitors,
  (SELECT all_visitors FROM total)              AS all_visitors,
  ROUND(100.0 * (SELECT COUNT(*) FROM cands)
        / NULLIF((SELECT all_visitors FROM total), 0), 2) AS candidate_pct;

-- ---------------------------------------------------------------------------
-- Q6. How much are we already throwing away? Visitors the cadence sweep marked
--     bot-suspect, and visitors carrying an AI-referral label. If a large slice
--     of the Q4/Q5 candidates is already flagged bot_suspect, Beam is discarding
--     the exact traffic this programme wants to serve.
-- ---------------------------------------------------------------------------
\echo ''
\echo '=== Q6. Already-suppressed / already-labelled visitors ==='
SELECT
  COUNT(*)                                                        AS visitors_90d,
  SUM(CASE WHEN is_bot_suspect THEN 1 ELSE 0 END)                 AS bot_suspect,
  SUM(CASE WHEN do_not_resolve THEN 1 ELSE 0 END)                 AS do_not_resolve,
  SUM(CASE WHEN ai_source IS NOT NULL THEN 1 ELSE 0 END)          AS ai_referred,
  SUM(CASE WHEN COALESCE(first_touch_referrer,'') = '' THEN 1 ELSE 0 END) AS empty_referrer
FROM visitors
WHERE last_seen >= now() - interval '90 days';

-- ---------------------------------------------------------------------------
-- Q7. AI-referral labels actually present (sanity check on the existing feature).
-- ---------------------------------------------------------------------------
\echo ''
\echo '=== Q7. ai_source distribution ==='
SELECT ai_source, COUNT(*) AS visitors
FROM visitors
WHERE last_seen >= now() - interval '90 days'
  AND ai_source IS NOT NULL
GROUP BY 1
ORDER BY visitors DESC;
