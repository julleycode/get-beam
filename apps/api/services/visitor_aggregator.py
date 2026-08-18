import math
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import delete, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.models.database import apply_long_job_statement_timeout
from apps.api.models.visitor import ResolutionLog, Visitor
from apps.api.services.ai_referral import classify_ai_source

logger = structlog.get_logger()

FUNNEL_STAGES: dict[int, list[str]] = {
    1: ["home", "blog", "about"],
    2: ["features", "how-it-works", "use-cases", "integrations"],
    3: ["pricing", "plans", "comparison", "demo", "contact"],
    4: ["signup", "checkout", "buy", "subscribe", "trial"],
}

SOCIAL_DOMAINS = ("twitter", "facebook", "linkedin", "x.com", "t.co", "fb.com")
SEARCH_DOMAINS = ("google", "bing", "duckduckgo", "yahoo", "baidu")


def _is_homepage(page: str) -> bool:
    from urllib.parse import urlparse
    try:
        path = urlparse(page).path if "://" in page else page
    except Exception:
        path = page
    return path.rstrip("/") == ""


def _classify_funnel_stages(pages_visited: list[str]) -> set[int]:
    stages_hit: set[int] = set()
    for page in pages_visited:
        if _is_homepage(page):
            stages_hit.add(1)
            continue
        lower = page.lower()
        for stage, keywords in FUNNEL_STAGES.items():
            if any(kw in lower for kw in keywords):
                stages_hit.add(stage)
    return stages_hit


def _score_referrer(
    top_referrer: str | None,
    utm_source: str | None,
    utm_medium: str | None,
) -> float:
    medium = (utm_medium or "").lower()
    ref = (top_referrer or "").lower()
    source = (utm_source or "").lower()

    if medium in ("cpc", "ppc", "paid"):
        return 3.0
    if medium == "email":
        return 8.0
    if medium == "social" or any(d in ref for d in SOCIAL_DOMAINS):
        return 3.0

    if any(d in ref for d in SEARCH_DOMAINS) or any(d in source for d in SEARCH_DOMAINS):
        return 10.0
    if not ref or ref == "direct":
        return 10.0

    if ref:
        return 5.0

    return 0.0


def _decay_multiplier(last_seen: datetime) -> float:
    now = datetime.now(timezone.utc)
    if last_seen.tzinfo is None:
        now = datetime.utcnow()
    hours = (now - last_seen).total_seconds() / 3600

    if hours < 24:
        return 1.0
    if hours < 168:
        return 0.9
    if hours < 720:
        return 0.7
    if hours < 2160:
        return 0.4
    return 0.2


def calculate_intent_score(
    first_seen: datetime,
    last_seen: datetime,
    total_sessions: int,
    max_scroll_depth: int,
    avg_time_on_page: float,
    pages_visited: list[str],
    top_referrer: str | None = None,
    utm_source: str | None = None,
    utm_medium: str | None = None,
) -> float:
    score = 0.0

    if total_sessions >= 3:
        score += 25
    elif total_sessions >= 2:
        score += 15

    if max_scroll_depth >= 75:
        score += 15

    if avg_time_on_page > 60:
        score += 10

    if total_sessions >= 2:
        if first_seen.tzinfo is None:
            fs = first_seen
            ls = last_seen.replace(tzinfo=None) if last_seen.tzinfo else last_seen
        else:
            fs = first_seen
            ls = last_seen if last_seen.tzinfo else last_seen.replace(tzinfo=first_seen.tzinfo)
        span_days = max((ls - fs).total_seconds() / 86400, 0)
        avg_gap = span_days / max(total_sessions - 1, 1)
        if avg_gap < 2:
            score += 15
        elif avg_gap < 5:
            score += 8

    stages = _classify_funnel_stages(pages_visited)
    stage_count = len(stages)
    if stage_count >= 4:
        score += 15
    elif stage_count == 3:
        score += 10
    elif stage_count == 2:
        score += 5

    score += _score_referrer(top_referrer, utm_source, utm_medium)

    decay = _decay_multiplier(last_seen)
    return min(score * decay, 100.0)


def _strip_tz(dt: datetime) -> datetime:
    """Strip timezone info to match TIMESTAMP WITHOUT TIME ZONE columns."""
    if dt.tzinfo is not None:
        return dt.replace(tzinfo=None)
    return dt


async def _upsert_visitor(
    db: AsyncSession,
    site_id: str,
    visitor_id: str,
    first_seen: datetime,
    last_seen: datetime,
    total_pageviews: int,
    total_sessions: int,
    max_scroll_depth: int,
    avg_time_on_page: float,
    pages_visited: list[str],
    top_referrer: str | None,
    utm_source: str | None,
    utm_medium: str | None,
    country_code: str | None,
    device_type: str | None,
    ip_address: str | None,
    first_touch_referrer: str | None = None,
    do_not_resolve: bool = False,
    is_abuse_flagged: bool = False,
    has_unstable_fingerprint: bool = False,
) -> None:
    """Upsert a single visitor row into the visitors table."""
    if avg_time_on_page is None or (isinstance(avg_time_on_page, float) and math.isnan(avg_time_on_page)):
        avg_time_on_page = 0.0

    intent = calculate_intent_score(
        first_seen=first_seen.replace(tzinfo=timezone.utc) if first_seen.tzinfo is None else first_seen,
        last_seen=last_seen.replace(tzinfo=timezone.utc) if last_seen.tzinfo is None else last_seen,
        total_sessions=total_sessions,
        max_scroll_depth=max_scroll_depth,
        avg_time_on_page=avg_time_on_page,
        pages_visited=pages_visited or [],
        top_referrer=top_referrer,
        utm_source=utm_source,
        utm_medium=utm_medium,
    )

    first_seen = _strip_tz(first_seen)
    last_seen = _strip_tz(last_seen)

    # ADDITIVE ATTRIBUTION METADATA ONLY. ai_source labels the AI answer engine
    # that referred a HUMAN click; it never sets source_agent_visit_id and never
    # gates emailability. AI-referred humans stay ordinary emailable visits.
    ai_source = classify_ai_source(first_touch_referrer)

    stmt = pg_insert(Visitor).values(
        site_id=site_id,
        visitor_id=visitor_id,
        first_seen=first_seen,
        last_seen=last_seen,
        total_pageviews=total_pageviews,
        total_sessions=total_sessions,
        avg_time_on_page=avg_time_on_page,
        max_scroll_depth=max_scroll_depth,
        pages_visited=pages_visited or [],
        top_referrer=top_referrer or None,
        first_touch_referrer=first_touch_referrer or None,
        ai_source=ai_source,
        utm_source=utm_source or None,
        utm_medium=utm_medium or None,
        country_code=country_code or None,
        device_type=device_type or None,
        ip_address=ip_address or None,
        intent_score=intent,
        do_not_resolve=do_not_resolve,
        is_abuse_flagged=is_abuse_flagged,
        has_unstable_fingerprint=has_unstable_fingerprint,
    ).on_conflict_do_update(
        index_elements=["site_id", "visitor_id"],
        set_={
            # Ingest may have inserted a FP/svid stub with first_seen≈now; prefer
            # the true earliest event timestamp from this full recompute.
            "first_seen": text("LEAST(visitors.first_seen, EXCLUDED.first_seen)"),
            "last_seen": last_seen,
            # Full recompute each run → SET totals (not increment) to avoid double-counting.
            "total_pageviews": total_pageviews,
            "total_sessions": total_sessions,
            "avg_time_on_page": avg_time_on_page,
            "max_scroll_depth": text("GREATEST(visitors.max_scroll_depth, :new_scroll)").bindparams(new_scroll=max_scroll_depth),
            "pages_visited": pages_visited or [],
            # SET (not increment) — full-recompute contract. first_touch_referrer
            # and its derived ai_source are recomputed from the entry pageview
            # each run. Both stay attribution-only (never source_agent_visit_id).
            "first_touch_referrer": first_touch_referrer or None,
            "ai_source": ai_source,
            "ip_address": ip_address or Visitor.ip_address,
            "intent_score": intent,
            # Sticky opt-out: once true it stays true, even if a later recompute
            # sees events without the flag (e.g. a different browser/session).
            "do_not_resolve": text("visitors.do_not_resolve OR EXCLUDED.do_not_resolve"),
            # Sticky abuse marker, same semantics as do_not_resolve above: once a
            # visitor's traffic looked like a flood, a later clean recompute must
            # not launder it back into outreach eligibility.
            "is_abuse_flagged": text(
                "visitors.is_abuse_flagged OR EXCLUDED.is_abuse_flagged"
            ),
            # Sticky farbled marker (WS2), same semantics as the two above: a
            # browser that rotates its fingerprint does not stop doing so
            # because one later window happened to carry no farbled event.
            "has_unstable_fingerprint": text(
                "visitors.has_unstable_fingerprint OR EXCLUDED.has_unstable_fingerprint"
            ),
            "updated_at": datetime.utcnow(),
        },
    )
    await db.execute(stmt)


# ─── Aggregation SQL (capacity-hardening Phase 3 / W1) ────────────────────────
# ONE template with four insertion points. With since=None every placeholder
# expands to the empty string / today's exact expression, so the emitted SQL is
# BYTE-IDENTICAL to the pre-change query (contract E4: append, never rewrite).
# The incremental variant only ADDS a lookback bound, a window filter, a
# first-in-window marker, and a delta-shaped session expression.
_DEFAULT_SESSIONS_EXPR = "MAX(session_num) FILTER (WHERE NOT is_flagged_abuse)"
# Incremental session DELTA. `is_new_session` is 1 when the gap to the previous
# event is > 30 min. `is_first_in_window` is 1 when this visitor has NO
# predecessor inside the read window at all — and because the read window starts
# a full 30 minutes BEFORE the watermark, "no predecessor in the window" can only
# mean either a brand-new visitor (session 1) or a gap > 30 min (a new session).
# Either way it contributes exactly one session, which is why the two cases are
# OR-ed rather than special-cased.
_INCREMENTAL_SESSIONS_EXPR = (
    "SUM(CASE WHEN is_new_session = 1 OR is_first_in_window = 1 THEN 1 ELSE 0 END)"
    " FILTER (WHERE NOT is_flagged_abuse)"
)
_INCREMENTAL_BOUNDARY_EXTRA_COLS = """,
                CASE
                    WHEN LAG(created_at) OVER (
                        PARTITION BY visitor_id ORDER BY created_at
                    ) IS NULL THEN 1
                    ELSE 0
                END AS is_first_in_window"""

_AGGREGATE_SQL_TEMPLATE = """
        WITH session_boundaries AS (
            SELECT
                visitor_id, created_at, event_type, url, referrer,
                utm_source, utm_medium, country_code, device_type,
                scroll_depth, time_on_page, ip_address, optout, is_flagged_abuse,
                farbled,
                CASE
                    WHEN created_at - LAG(created_at) OVER (
                        PARTITION BY visitor_id ORDER BY created_at
                    ) > INTERVAL '30 minutes' THEN 1
                    ELSE 0
                END AS is_new_session{boundary_extra_cols}
            FROM events
            WHERE site_id = :site_id{lookback_clause}
        ),
        session_numbered AS (
            SELECT *,
                SUM(is_new_session) OVER (
                    PARTITION BY visitor_id ORDER BY created_at
                ) + 1 AS session_num
            FROM session_boundaries
        )
        SELECT
            visitor_id,
            MIN(created_at) FILTER (WHERE NOT is_flagged_abuse) AS first_seen,
            MAX(created_at) FILTER (WHERE NOT is_flagged_abuse) AS last_seen,
            COUNT(*) FILTER (WHERE event_type = 'pageview' AND NOT is_flagged_abuse) AS total_pageviews,
            {sessions_expr} AS total_sessions,
            COALESCE(MAX(scroll_depth) FILTER (WHERE NOT is_flagged_abuse), 0) AS max_scroll_depth,
            COALESCE(AVG(time_on_page) FILTER (WHERE time_on_page > 0 AND NOT is_flagged_abuse), 0) AS avg_time_on_page,
            ARRAY_AGG(DISTINCT url) FILTER (WHERE event_type = 'pageview' AND url != '' AND NOT is_flagged_abuse) AS pages_visited,
            MAX(referrer) FILTER (WHERE referrer != '' AND NOT is_flagged_abuse) AS top_referrer,
            (ARRAY_AGG(referrer ORDER BY created_at ASC) FILTER (WHERE event_type = 'pageview' AND NOT is_flagged_abuse))[1] AS first_touch_referrer,
            MAX(utm_source) FILTER (WHERE utm_source != '' AND NOT is_flagged_abuse) AS utm_source,
            MAX(utm_medium) FILTER (WHERE utm_medium != '' AND NOT is_flagged_abuse) AS utm_medium,
            MAX(country_code) FILTER (WHERE country_code != '' AND NOT is_flagged_abuse) AS country_code,
            MAX(device_type) FILTER (WHERE device_type != '' AND NOT is_flagged_abuse) AS device_type,
            (ARRAY_AGG(ip_address ORDER BY created_at DESC) FILTER (WHERE ip_address != '' AND NOT is_flagged_abuse))[1] AS latest_ip,
            BOOL_OR(optout) AS do_not_resolve,
            BOOL_OR(is_flagged_abuse) AS abuse_flagged,
            BOOL_OR(farbled) AS has_unstable_fingerprint
        FROM session_numbered{window_clause}
        GROUP BY visitor_id
    """

# LAG needs to see at least one event BEFORE the watermark to decide whether the
# first in-window event opens a new session — so the incremental run READS from
# `since - 30 minutes` but only MERGES rows strictly after `since`.
BOUNDARY_LOOKBACK = timedelta(minutes=30)


def build_aggregate_sql(since: datetime | None) -> str:
    """Return the aggregation SQL. `since=None` reproduces today's query verbatim."""
    if since is None:
        return _AGGREGATE_SQL_TEMPLATE.format(
            boundary_extra_cols="",
            lookback_clause="",
            sessions_expr=_DEFAULT_SESSIONS_EXPR,
            window_clause="",
        )
    return _AGGREGATE_SQL_TEMPLATE.format(
        boundary_extra_cols=_INCREMENTAL_BOUNDARY_EXTRA_COLS,
        lookback_clause="\n              AND created_at > :lookback_start",
        sessions_expr=_INCREMENTAL_SESSIONS_EXPR,
        window_clause="\n        WHERE created_at > :since",
    )


async def _snapshot_unresolvable_ips(db: AsyncSession, site_id: str) -> dict[str, str | None]:
    """Pre-rollup snapshot of `{visitor_id: ip_address}` for unresolvable rows.

    Sites are small (hundreds of rows), so a whole-site snapshot is cheaper than
    trying to guess which visitors the rollup is about to touch. Fail-open: any
    error yields an empty snapshot, which makes the revive pass a no-op.
    """
    try:
        result = await db.execute(
            select(Visitor.visitor_id, Visitor.ip_address).where(
                Visitor.site_id == site_id,
                Visitor.identity_status == "unresolvable",
            )
        )
        return {row[0]: row[1] for row in result.all()}
    except Exception as exc:
        logger.warning("unresolvable_snapshot_failed", site_id=site_id, error=str(exc))
        return {}


async def revive_returning_unresolvable(
    db: AsyncSession,
    site_id: str,
    pre_snapshot: dict[str, str | None],
) -> int:
    """Re-queue `unresolvable` visitors whose IP changed during this rollup.

    A visitor marked `identity_status='unresolvable'` was previously dead forever:
    the resolution sweep only selects `'anonymous'` rows, so no later visit could
    ever retry them. That matters because the DB carries a large backlog of rows
    whose stored IP is a Cloudflare EDGE ip (junk, pre-dating the
    CF-Connecting-IP fix) — those visitors were never actually resolvable from the
    IP we had. The moment such a visitor returns and the rollup overwrites
    `ip_address` with a real address, that is a genuinely NEW provider query and
    must be retried.

    So: compare the pre-rollup IP against the post-rollup IP; for every visitor
    whose IP changed (`IS DISTINCT FROM` semantics — NULL → real counts), flip the
    status back to `anonymous` and purge only that visitor's FAILED
    `resolution_logs` so the 30-day no-retry gate sees a fresh candidate.
    Successful rows are NEVER deleted (billing/usage history).

    Fail-open: a failure here logs and returns 0; it never breaks aggregation.
    """
    if not pre_snapshot:
        return 0

    try:
        ids = list(pre_snapshot.keys())
        result = await db.execute(
            select(Visitor.visitor_id, Visitor.ip_address).where(
                Visitor.site_id == site_id,
                Visitor.visitor_id.in_(ids),
            )
        )
        changed = [
            vid for vid, new_ip in result.all()
            if pre_snapshot.get(vid) != new_ip
        ]
        if not changed:
            return 0

        await db.execute(
            update(Visitor)
            .where(
                Visitor.site_id == site_id,
                Visitor.visitor_id.in_(changed),
                # Guard: never clobber a concurrent identify.
                Visitor.identity_status == "unresolvable",
            )
            .values(identity_status="anonymous")
        )
        await db.execute(
            delete(ResolutionLog).where(
                ResolutionLog.site_id == site_id,
                ResolutionLog.visitor_id.in_(changed),
                ResolutionLog.success.is_(False),
            )
        )
        await db.commit()
        # Count only — never log IPs (PII rule).
        logger.info("unresolvable_revived", site_id=site_id, revived=len(changed))
        return len(changed)
    except Exception as exc:
        await db.rollback()
        logger.warning("unresolvable_revive_failed", site_id=site_id, error=str(exc))
        return 0


async def aggregate_visitors_for_site(
    db: AsyncSession,
    site_id: str,
    since: datetime | None = None,
) -> int:
    """Aggregate visitors from the PostgreSQL events table.

    Uses window functions to detect real session boundaries:
    a new session starts when there is a gap > 30 minutes between consecutive events.

    `since=None` (the default, and the ONLY behavior when
    `aggregation_incremental_enabled` is False) aggregates the FULL event history
    per visitor — an idempotent, self-healing recompute where totals are SET (not
    incremented) on conflict. This is also the repair path: it is the sole writer
    of `avg_time_on_page` and `intent_score` once the incremental flag is on (D7).

    `since` set selects the watermark-incremental path: only events created after
    the watermark are MERGED (additively), while the read window starts 30 minutes
    earlier so `LAG` can still classify the first in-window event's session
    boundary. Incremental runs never write `avg_time_on_page` / `intent_score`
    (D7) and never overwrite `first_touch_referrer` / `ai_source` / `ip_address`
    (D6 / E13 / E14).
    """
    # Check if events table exists
    check = await db.execute(text(
        "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'events')"
    ))
    if not check.scalar():
        return 0

    # Pre-rollup IP snapshot for the unresolvable-revive pass (see
    # revive_returning_unresolvable): must be read BEFORE the upsert overwrites
    # ip_address, so a returning visitor's IP change is detectable.
    unresolvable_pre = await _snapshot_unresolvable_ips(db, site_id)

    # Session-aware aggregation using window functions:
    # 1. Detect session boundaries (gap > 30 min between events)
    # 2. Count distinct sessions per visitor
    # 3. Extract latest IP address
    params: dict = {"site_id": site_id}
    if since is not None:
        params["since"] = _strip_tz(since)
        params["lookback_start"] = _strip_tz(since - BOUNDARY_LOOKBACK)

    # Stamp the watermark from the DB clock BEFORE reading, so events that land
    # mid-run are picked up by the NEXT run rather than silently skipped.
    run_started_at = None
    if since is not None:
        run_started_at = (await db.execute(text("SELECT now()"))).scalar()

    result = await db.execute(text(build_aggregate_sql(since)), params)

    rows = result.fetchall()
    count = 0

    if since is None:
        for row in rows:
            (
                visitor_id, first_seen, last_seen, total_pageviews,
                total_sessions, max_scroll_depth, avg_time_on_page, pages_visited,
                top_referrer, first_touch_referrer, utm_source, utm_medium,
                country_code, device_type, latest_ip, do_not_resolve, abuse_flagged,
                unstable_fp,
            ) = row

            await _upsert_visitor(
                db, site_id, visitor_id,
                first_seen or datetime.utcnow(),
                last_seen or datetime.utcnow(),
                total_pageviews or 0,
                total_sessions or 1,
                max_scroll_depth or 0,
                avg_time_on_page or 0.0,
                pages_visited or [],
                top_referrer, utm_source, utm_medium, country_code, device_type,
                latest_ip,
                first_touch_referrer=first_touch_referrer,
                do_not_resolve=bool(do_not_resolve),
                is_abuse_flagged=bool(abuse_flagged),
                has_unstable_fingerprint=bool(unstable_fp),
            )
            count += 1
    else:
        count = await _bulk_upsert_visitors_incremental(db, site_id, rows)

    await db.commit()

    # SET LOCAL dies at COMMIT. Re-apply so revive / company resolution
    # cannot inherit a 30s request budget (F5 tail).
    await apply_long_job_statement_timeout(db)

    # Returning-visitor revive: a fresh IP on a previously unresolvable row is a
    # genuinely new provider query, so re-queue it for the resolution sweep.
    await revive_returning_unresolvable(db, site_id, unresolvable_pre)

    # Revive may COMMIT; re-apply before watermark / _resolve_companies.
    await apply_long_job_statement_timeout(db)

    # Watermark advances ONLY after a successful commit of this run's upserts
    # (checklist item 9). A crash before this point simply re-reads the same
    # half-open window next time; because the window is `created_at > watermark`
    # and never a rolling "last N hours", a re-read can never double-merge.
    if since is not None and run_started_at is not None:
        await advance_watermark(db, site_id, run_started_at)

    # Phase 4: Resolve IP → company domain for visitors that don't have one yet.
    # This already ran AFTER the commit above, so nothing needs "moving"; the
    # remaining Phase 3 change is the DISPATCH half — behind the incremental flag
    # the external lookups no longer sit on the awaited ingest path.
    if since is not None:
        _dispatch_company_resolution(site_id)
    else:
        await _resolve_companies(db, site_id)

    logger.info(
        "visitors_aggregated",
        site_id=site_id,
        count=count,
        incremental=since is not None,
    )
    return count


async def advance_watermark(db: AsyncSession, site_id: str, stamp: datetime) -> None:
    """Stamp `sites.last_aggregated_at` post-commit. Never fails the run.

    Public so ingest/bootstrap can stamp after a successful *full* run without
    duplicating SQL. ``aggregate_visitors_for_site`` still stamps only when
    ``since is not None`` — a full aggregator call (``since=None``) does not.
    """
    from apps.api.models.site import Site

    try:
        await db.execute(
            update(Site)
            .where(Site.site_id == site_id)
            .values(last_aggregated_at=_strip_tz(stamp))
        )
        await db.commit()
    except Exception as exc:
        await db.rollback()
        logger.warning("aggregation_watermark_advance_failed", site_id=site_id, error=str(exc))


async def get_aggregation_watermark(db: AsyncSession, site_id: str) -> datetime | None:
    """Return the site's incremental watermark, or None when it has never run.

    None means "no bounded window is safe yet" — the caller must full-recompute.
    """
    from apps.api.models.site import Site

    try:
        result = await db.execute(
            select(Site.last_aggregated_at).where(Site.site_id == site_id)
        )
        return result.scalar_one_or_none()
    except Exception as exc:
        logger.warning("aggregation_watermark_read_failed", site_id=site_id, error=str(exc))
        return None


# Merge expressions for the incremental bulk upsert. Every column here is either
# additive or keep-existing — NEVER a plain SET, because a bounded run can only
# see the rows inside its own window.
#
# DELIBERATELY ABSENT (D7): `avg_time_on_page` and `intent_score`. A window-only
# value for either would be WRONG, not merely stale — avg_time_on_page has no
# correct weighted merge without a stored contributing-event count, and
# intent_score is computed in Python from all-time inputs. The full-recompute
# repair sweep is their sole writer.
_INCREMENTAL_SET = {
    "last_seen": text("GREATEST(visitors.last_seen, EXCLUDED.last_seen)"),
    "total_pageviews": text("visitors.total_pageviews + EXCLUDED.total_pageviews"),
    "total_sessions": text("visitors.total_sessions + EXCLUDED.total_sessions"),
    "max_scroll_depth": text("GREATEST(visitors.max_scroll_depth, EXCLUDED.max_scroll_depth)"),
    # JSONB array union — order-insensitive, duplicate-free.
    "pages_visited": text(
        "(SELECT COALESCE(jsonb_agg(DISTINCT p), '[]'::jsonb) FROM jsonb_array_elements("
        "COALESCE(visitors.pages_visited, '[]'::jsonb) || COALESCE(EXCLUDED.pages_visited, '[]'::jsonb)"
        ") AS p)"
    ),
    # D6 — keep-existing-if-set. A window-only recompute would otherwise
    # overwrite the true chronological first touch (the exact bug guarded by
    # test_first_touch_beats_lexicographic_max).
    "first_touch_referrer": text(
        "COALESCE(NULLIF(visitors.first_touch_referrer, ''), EXCLUDED.first_touch_referrer)"
    ),
    # E13 — ai_source is conditioned on whether the REFERRER was kept, never
    # COALESCEd independently. classify_ai_source() returns NULL for every
    # ordinary referrer, so a symmetric COALESCE would let a later AI-referred
    # pageview stamp "Arrived via ChatGPT" onto a visitor whose kept first touch
    # is google.com — a false badge on the common case.
    "ai_source": text(
        "CASE WHEN NULLIF(visitors.first_touch_referrer, '') IS NOT NULL "
        "THEN visitors.ai_source ELSE EXCLUDED.ai_source END"
    ),
    # E14 — preserve the existing keep-if-set semantic (`ip_address or
    # Visitor.ip_address` in the single-row path). A window with no IP must never
    # blank a stored one.
    "ip_address": text("COALESCE(EXCLUDED.ip_address, visitors.ip_address)"),
    # Sticky flags — unchanged from the full-recompute path.
    "do_not_resolve": text("visitors.do_not_resolve OR EXCLUDED.do_not_resolve"),
    "is_abuse_flagged": text("visitors.is_abuse_flagged OR EXCLUDED.is_abuse_flagged"),
    "has_unstable_fingerprint": text(
        "visitors.has_unstable_fingerprint OR EXCLUDED.has_unstable_fingerprint"
    ),
}


async def _bulk_upsert_visitors_incremental(
    db: AsyncSession,
    site_id: str,
    rows: list,
) -> int:
    """Chunked bulk upsert for the incremental path (decision D4).

    One round-trip per chunk instead of one per visitor, which shortens the
    row-lock window proportionally. `site_id` stays in both the values and the
    conflict index elements so tenant scoping is structurally preserved (C6).
    """
    from apps.api.config import settings

    if not rows:
        return 0

    payload: list[dict] = []
    for row in rows:
        (
            visitor_id, first_seen, last_seen, total_pageviews,
            total_sessions, max_scroll_depth, avg_time_on_page, pages_visited,
            top_referrer, first_touch_referrer, utm_source, utm_medium,
            country_code, device_type, latest_ip, do_not_resolve, abuse_flagged,
            unstable_fp,
        ) = row

        first_seen = _strip_tz(first_seen or datetime.utcnow())
        last_seen = _strip_tz(last_seen or datetime.utcnow())
        payload.append({
            "site_id": site_id,
            "visitor_id": visitor_id,
            "first_seen": first_seen,
            "last_seen": last_seen,
            "total_pageviews": total_pageviews or 0,
            # DELTA, not a total — and `or 1` would be WRONG here. A window whose
            # only event continues the previous session yields a delta of 0, and
            # coercing that to 1 invents a session on every batch. A genuinely
            # new visitor always yields >= 1 via is_first_in_window.
            "total_sessions": total_sessions if total_sessions is not None else 0,
            # Insert-only defaults for the two DESCOPED columns: a brand-new row
            # needs *some* value, and the repair sweep overwrites both. They are
            # absent from _INCREMENTAL_SET, so an existing row is never touched.
            "avg_time_on_page": avg_time_on_page or 0.0,
            "max_scroll_depth": max_scroll_depth or 0,
            "pages_visited": pages_visited or [],
            "top_referrer": top_referrer or None,
            "first_touch_referrer": first_touch_referrer or None,
            "ai_source": classify_ai_source(first_touch_referrer),
            "utm_source": utm_source or None,
            "utm_medium": utm_medium or None,
            "country_code": country_code or None,
            "device_type": device_type or None,
            "ip_address": latest_ip or None,
            "intent_score": 0.0,
            "do_not_resolve": bool(do_not_resolve),
            "is_abuse_flagged": bool(abuse_flagged),
            "has_unstable_fingerprint": bool(unstable_fp),
        })

    chunk_size = max(settings.aggregation_upsert_chunk_size, 1)
    set_ = dict(_INCREMENTAL_SET)
    set_["updated_at"] = datetime.utcnow()

    for start in range(0, len(payload), chunk_size):
        chunk = payload[start:start + chunk_size]
        stmt = pg_insert(Visitor).values(chunk).on_conflict_do_update(
            index_elements=["site_id", "visitor_id"],
            set_=set_,
        )
        await db.execute(stmt)

    return len(payload)


# Strong refs so dispatched resolutions are not garbage-collected mid-flight.
_resolution_tasks: set = set()


def _dispatch_company_resolution(site_id: str) -> None:
    """Fire company resolution off the ingest path (checklist item 6).

    MANDATORY GUARD: `_upsert_company` merges with unconditional
    `companies.total_visitors + 1` / `+ EXCLUDED.total_sessions` /
    `+ EXCLUDED.total_pageviews`. Two concurrent resolutions for one site would
    therefore INFLATE company counters. Dispatch is only legal behind a
    single-flight lock, so this takes `agg:resolve:{site_id}` and never runs
    without it — including when Redis is degraded (fail CLOSED: a skipped
    resolution is retried by the next run, an inflated counter is permanent).
    """
    import asyncio

    async def _run() -> None:
        from apps.api.config import settings
        from apps.api.models.database import async_session
        from apps.api.services import aggregation_debounce as _dbnc

        key = _dbnc.resolve_lock_key(site_id)
        acquired = await _dbnc.try_acquire(key, settings.aggregation_min_interval_seconds)
        if acquired is not True:
            logger.info(
                "company_resolution_skipped_single_flight",
                site_id=site_id,
                redis_degraded=acquired is None,
            )
            return
        try:
            async with async_session() as db:
                await _resolve_companies(db, site_id)
        except Exception as exc:
            logger.warning("company_resolution_dispatch_failed", site_id=site_id, error=str(exc))
        finally:
            await _dbnc.release(key)

    try:
        task = asyncio.create_task(_run())
        _resolution_tasks.add(task)
        task.add_done_callback(_resolution_tasks.discard)
    except RuntimeError:
        # No running loop (sync/Celery context) — nothing to dispatch onto.
        logger.info("company_resolution_dispatch_no_loop", site_id=site_id)


async def _resolve_companies(db: AsyncSession, site_id: str) -> None:
    """Resolve company domains from IP for visitors missing company_domain."""
    try:
        from apps.api.services.company_resolver import resolve_company_cached
        from apps.api.services.agent_visitor_filters import human_only_visitor_filter

        # Get visitors with IP but no company_domain (limit 20 per run to avoid slowdowns)
        result = await db.execute(
            select(Visitor).where(
                Visitor.site_id == site_id,
                Visitor.ip_address.isnot(None),
                Visitor.ip_address != "",
                (Visitor.company_domain.is_(None)) | (Visitor.company_domain == ""),
                # AC2 (GUARD #2): the synthetic agent-derived rows are resolved
                # only by the company-resolution sweep — never by this
                # uncoordinated 2nd aggregator pass.
                human_only_visitor_filter(),
            ).limit(20)
        )
        visitors = result.scalars().all()

        if not visitors:
            return

        resolved = 0
        for visitor in visitors:
            # Pass db so the durable company_graph write-through/read-first can
            # activate when company_graph_enabled is True (flag off → unchanged).
            domain = await resolve_company_cached(visitor.ip_address, db=db)
            if domain:
                visitor.company_domain = domain
                resolved += 1

                # Upsert into companies table
                await _upsert_company(db, site_id, domain, visitor)

        if resolved:
            await db.commit()
            logger.info("companies_resolved", site_id=site_id, resolved=resolved, total=len(visitors))

    except Exception as e:
        logger.warning("company_resolution_failed", site_id=site_id, error=str(e))


async def _upsert_company(
    db: AsyncSession,
    site_id: str,
    domain: str,
    visitor: Visitor,
) -> None:
    """Upsert a company row from a resolved visitor."""
    from apps.api.models.company import Company

    stmt = pg_insert(Company).values(
        site_id=site_id,
        domain=domain,
        total_visitors=1,
        total_sessions=visitor.total_sessions or 1,
        total_pageviews=visitor.total_pageviews or 0,
        intent_score=visitor.intent_score or 0.0,
        first_seen=visitor.first_seen or datetime.utcnow(),
        last_seen=visitor.last_seen or datetime.utcnow(),
    ).on_conflict_do_update(
        index_elements=["site_id", "domain"],
        set_={
            "total_visitors": text("companies.total_visitors + 1"),
            "total_sessions": text("companies.total_sessions + EXCLUDED.total_sessions"),
            "total_pageviews": text("companies.total_pageviews + EXCLUDED.total_pageviews"),
            "intent_score": text(
                "LEAST("
                "  GREATEST(companies.intent_score, EXCLUDED.intent_score)"
                "  + LEAST(companies.intent_score, EXCLUDED.intent_score) * 0.3,"
                "  100)"
            ),
            "last_seen": text("GREATEST(companies.last_seen, EXCLUDED.last_seen)"),
            "updated_at": datetime.utcnow(),
        },
    )
    await db.execute(stmt)
