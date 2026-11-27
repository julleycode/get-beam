"""Daily read-only ad-performance ingest (ad-insights-seo-aeo_27-11-26, A5).

Per site: every ``connected`` Meta/Google ``AdConnection`` -> refresh token ->
re-check status -> ``fetch_ad_performance`` -> idempotent upsert on
(connection_id, platform_ad_id, date). Errors are isolated per connection and
logged by id only — never ad copy, never tokens.
"""

from datetime import date, datetime, timedelta, timezone

import structlog
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.config import settings
from apps.api.models.ad_connection import AdConnection
from apps.api.models.ad_performance import AdPerformanceDaily

logger = structlog.get_logger()

INSIGHT_PROVIDERS = ("meta", "google")
_LOCK_KEY = "ad_insights_daily"

# Defensive caps on stored third-party text.
_CAP_HEADLINE = 1000
_CAP_BODY = 2000
_CAP_URL = 2000
_CAP_CAMPAIGN = 500


async def try_acquire_lock(db: AsyncSession) -> bool | None:
    """True = acquired, False = held elsewhere, None = unsupported/errored."""
    try:
        result = await db.execute(
            text("SELECT pg_try_advisory_lock(hashtext(:key))"), {"key": _LOCK_KEY}
        )
        return bool(result.scalar())
    except Exception as exc:  # noqa: BLE001
        logger.warning("ad_insights_lock_unavailable", error=type(exc).__name__)
        return None


async def release_lock(db: AsyncSession) -> None:
    try:
        await db.execute(
            text("SELECT pg_advisory_unlock(hashtext(:key))"), {"key": _LOCK_KEY}
        )
    except Exception:  # noqa: BLE001
        pass


async def ingest_connection(db: AsyncSession, conn: AdConnection) -> int:
    """Fetch + upsert one connection's lookback window. Returns rows upserted."""
    from apps.api.services.ads.factory import get_provider
    from apps.api.services.ads_push import fresh_access_token

    await fresh_access_token(db, conn)
    if conn.status != "connected":  # N-2: refresh failure flips status to error
        logger.info("ad_insights_skip_connection", connection_id=str(conn.id), status=conn.status)
        return 0

    until = datetime.now(timezone.utc).date()
    since = until - timedelta(days=max(1, settings.ad_insights_lookback_days))
    provider = get_provider(conn.provider)
    rows = await provider.fetch_ad_performance(conn, since, until)
    if not rows:
        return 0

    values = [
        {
            "site_id": conn.site_id,
            "connection_id": conn.id,
            "provider": conn.provider,
            "platform_ad_id": r.platform_ad_id[:100],
            "campaign_name": (r.campaign_name or "")[:_CAP_CAMPAIGN] or None,
            "headline": (r.headline or "")[:_CAP_HEADLINE] or None,
            "body": (r.body or "")[:_CAP_BODY] or None,
            "landing_url": (r.landing_url or "")[:_CAP_URL] or None,
            "date": r.date,
            "impressions": max(0, r.impressions),
            "clicks": max(0, r.clicks),
            "conversions": max(0.0, r.conversions),
        }
        for r in rows
    ]
    # Collapse duplicate keys inside one report (last wins) so a single
    # INSERT ... ON CONFLICT never touches the same row twice.
    dedup: dict[tuple, dict] = {}
    for v in values:
        dedup[(v["platform_ad_id"], v["date"])] = v
    values = list(dedup.values())

    stmt = pg_insert(AdPerformanceDaily).values(values)
    stmt = stmt.on_conflict_do_update(
        constraint="uq_ad_perf_conn_ad_date",
        set_={
            "campaign_name": stmt.excluded.campaign_name,
            "headline": stmt.excluded.headline,
            "body": stmt.excluded.body,
            "landing_url": stmt.excluded.landing_url,
            "impressions": stmt.excluded.impressions,
            "clicks": stmt.excluded.clicks,
            "conversions": stmt.excluded.conversions,
            "updated_at": datetime.now(timezone.utc),
        },
    )
    await db.execute(stmt)
    await db.commit()
    return len(values)


async def ingest_site(db: AsyncSession, site_id: str) -> int:
    conns = (
        await db.execute(
            select(AdConnection).where(
                AdConnection.site_id == site_id,
                AdConnection.provider.in_(INSIGHT_PROVIDERS),
                AdConnection.status == "connected",
            )
        )
    ).scalars().all()
    total = 0
    for conn in conns:
        try:
            total += await ingest_connection(db, conn)
        except Exception as exc:  # noqa: BLE001 — per-connection isolation
            await db.rollback()
            logger.warning(
                "ad_insights_ingest_failed",
                connection_id=str(conn.id),
                provider=conn.provider,
                error=type(exc).__name__,
            )
    return total


async def sites_with_ad_connections(db: AsyncSession) -> list[str]:
    rows = await db.execute(
        select(AdConnection.site_id)
        .where(
            AdConnection.provider.in_(INSIGHT_PROVIDERS),
            AdConnection.status == "connected",
        )
        .distinct()
    )
    return sorted(r[0] for r in rows.all())


async def run_ad_insights_once(db: AsyncSession, *, today: date | None = None) -> dict:
    """Daily job body: ingest -> rank -> suggest per site, under an advisory lock.

    Lock semantics mirror services/coop_expiry_sweep.py (G-1/E7): skip ONLY when
    the lock is held elsewhere (``is False``); proceed on ``None``; always
    unlock in ``finally``.
    """
    stats = {"sites": 0, "rows": 0, "suggestions": 0, "skipped": False}
    if not settings.ad_insights_enabled:
        return stats
    acquired = await try_acquire_lock(db)
    if acquired is False:
        logger.info("ad_insights_lock_held_skip")
        stats["skipped"] = True
        return stats
    try:
        from apps.api.services.content_opportunities import generate_for_site

        for site_id in await sites_with_ad_connections(db):
            stats["sites"] += 1
            stats["rows"] += await ingest_site(db, site_id)
            try:
                stats["suggestions"] += await generate_for_site(db, site_id, today=today)
            except Exception as exc:  # noqa: BLE001
                await db.rollback()
                logger.warning("ad_insights_suggest_failed", site_id=site_id, error=type(exc).__name__)
        logger.info("ad_insights_run_done", **{k: v for k, v in stats.items() if k != "skipped"})
        return stats
    finally:
        await release_lock(db)
