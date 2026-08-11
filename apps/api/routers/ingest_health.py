"""Operator observability for the ingest abuse-hardening layers (P5).

Answers the one question a raw event-table query cannot answer quickly during an
incident: is this traffic spike a FLOOD or an ORGANIC surge? Without this an
operator has to hand-write SQL against the events table mid-incident.

Also surfaces the rate-limiter storage backend. When Redis is unreachable slowapi
silently falls back to in-process ``memory://``, which makes every limit PER
REPLICA instead of global — a materially weaker guarantee that would otherwise be
visible only as one warning line at boot.
"""

from datetime import datetime, timedelta

import structlog
from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.config import settings as _celery_settings
from apps.api.dependencies import get_current_user, verify_site_access
from apps.api.models.api_usage import ApiUsageLog
from apps.api.models.database import get_db
from apps.api.models.event import Event
from apps.api.models.user import User
from apps.api.models.visitor import ResolutionLog, Visitor
from apps.api.services.identity_providers.base import (
    RESOLUTION_OUTCOME_PROVIDER_UNAVAILABLE,
)

logger = structlog.get_logger()

router = APIRouter()

# Share of recent events flagged, above which the shape reads as a flood rather
# than an organic surge. Calibration value, documented not empirically derived.
_FLOOD_RATIO_THRESHOLD = 0.5


def _limiter_storage_status() -> dict:
    """Report the limiter backend, distinguishing boot-time from live state.

    E3: the boot-time value is what slowapi actually resolved at import and is
    what the limiters are USING; it can go stale if Redis recovers later, so it
    is named explicitly rather than presented as "current". ``live_ping`` is a
    real round-trip taken now.
    """
    from apps.api.services.rate_limiter import storage_backend

    live: str
    try:
        import redis

        from apps.api.config import settings

        client = redis.Redis.from_url(settings.redis_url, socket_connect_timeout=2)
        client.ping()
        live = "reachable"
    except Exception:
        live = "unreachable"

    return {
        # What the limiters resolved at process start and are actually using.
        "backend_at_process_start": storage_backend(),
        # A live round-trip taken during THIS request.
        "redis_live_ping": live,
        # True when limits are per-replica rather than global right now.
        "degraded": storage_backend() != "redis" or live != "reachable",
    }


@router.get("/{site_id}/ingest-health")
async def get_ingest_health(
    site_id: str,
    window_minutes: int = Query(60, ge=1, le=1440),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Flood-vs-organic signal for one site's recent ingest traffic.

    Tenant-scoped through ``verify_site_access`` (Site.user_id), which 404s an
    unknown OR foreign site_id rather than 403ing, so the response never leaks
    which site_ids exist.
    """
    await verify_site_access(db, site_id, user)

    since = datetime.utcnow() - timedelta(minutes=window_minutes)

    totals = (
        await db.execute(
            select(
                func.count().label("total"),
                func.count()
                .filter(Event.is_flagged_abuse.is_(True))
                .label("flagged"),
                func.count(func.distinct(Event.visitor_id)).label("distinct_visitors"),
            ).where(Event.site_id == site_id, Event.created_at >= since)
        )
    ).one()

    total = int(totals.total or 0)
    flagged = int(totals.flagged or 0)
    distinct_visitors = int(totals.distinct_visitors or 0)
    flagged_ratio = (flagged / total) if total else 0.0

    # Sticky visitor-level privacy opt-out over the same window. One extra
    # aggregate over `visitors` (not `events` — the sticky flag is the number
    # `resolve()` gates on, and events is the largest table in the schema).
    optout = (
        await db.execute(
            select(
                func.count().label("visitors"),
                func.count()
                .filter(Visitor.do_not_resolve.is_(True))
                .label("opted_out"),
            ).where(Visitor.site_id == site_id, Visitor.last_seen >= since)
        )
    ).one()

    optout_visitors = int(optout.visitors or 0)
    optout_count = int(optout.opted_out or 0)

    # Identity-provider health over the same window. Two ledgers are needed
    # because they are deliberately disjoint: `_log_resolution` writes a
    # ResolutionLog row ONLY for match / no_match (an outage is not an attempt,
    # so it must not arm the 30-day retry lock or burn the daily budget), while
    # EVERY outcome mirrors into api_usage_logs. So a provider dying of
    # 401/403/402 vanishes from resolution_logs entirely — which is exactly how
    # the 2026-08-06 rb2b/pdl outage stayed invisible for four days.
    #
    # Both predicates are window-bounded on (site_id, created_at), matching
    # idx_resolution_logs_site_created and idx_api_usage_site_created, so
    # neither is a seq scan on an append-heavy table. No new index added.
    attempt_rows = (
        await db.execute(
            select(
                ResolutionLog.provider,
                func.count().label("attempts"),
                func.count().filter(ResolutionLog.success.is_(True)).label("successes"),
            )
            .where(ResolutionLog.site_id == site_id, ResolutionLog.created_at >= since)
            .group_by(ResolutionLog.provider)
        )
    ).all()

    unavailable_rows = (
        await db.execute(
            select(ApiUsageLog.provider, func.count().label("unavailable"))
            .where(
                ApiUsageLog.site_id == site_id,
                ApiUsageLog.created_at >= since,
                ApiUsageLog.category == "identity",
                ApiUsageLog.meta["outcome"].astext
                == RESOLUTION_OUTCOME_PROVIDER_UNAVAILABLE,
            )
            .group_by(ApiUsageLog.provider)
        )
    ).all()

    by_provider: dict[str, dict] = {}
    for row in attempt_rows:
        by_provider[row.provider] = {
            "provider": row.provider,
            "attempts": int(row.attempts or 0),
            "successes": int(row.successes or 0),
            "unavailable": 0,
        }
    for row in unavailable_rows:
        entry = by_provider.setdefault(
            row.provider,
            {"provider": row.provider, "attempts": 0, "successes": 0, "unavailable": 0},
        )
        entry["unavailable"] = int(row.unavailable or 0)

    providers = []
    for entry in by_provider.values():
        # calls = attempts + unavailable is the TRUE call count: the two ledgers
        # partition the outcomes, they do not overlap.
        calls = entry["attempts"] + entry["unavailable"]
        providers.append(
            {
                **entry,
                "calls": calls,
                "unavailable_rate": round(entry["unavailable"] / calls, 4)
                if calls
                else 0.0,
            }
        )
    providers.sort(key=lambda p: (-p["unavailable"], p["provider"]))

    if total == 0:
        signal = "no_traffic"
    elif flagged_ratio >= _FLOOD_RATIO_THRESHOLD:
        signal = "likely_flood"
    elif flagged > 0:
        signal = "mixed"
    else:
        signal = "organic"

    # Counts and ids only — no visitor PII of any kind (AC-9).
    return {
        "site_id": site_id,
        "window_minutes": window_minutes,
        "total_events": total,
        "flagged_events": flagged,
        "clean_events": total - flagged,
        "distinct_visitors": distinct_visitors,
        "flagged_ratio": round(flagged_ratio, 4),
        "flood_signal": signal,
        # Why identity coverage may look low: visitors who sent GPC/DNT are
        # refused by the resolver by design. Counts only, no PII (AC-9).
        "privacy_optout": {
            "visitors": optout_visitors,
            "opted_out": optout_count,
            "rate": round(optout_count / optout_visitors, 4)
            if optout_visitors
            else 0.0,
        },
        # Identity-provider health. Counts only, no PII (AC-9). Thresholds live
        # in the web helper (`resolution-health.ts`) — this stays raw counts so
        # the API never has to be redeployed to retune a warning band.
        "resolution_health": {
            "providers": providers,
            "total_calls": sum(p["calls"] for p in providers),
            "total_successes": sum(p["successes"] for p in providers),
            "total_unavailable": sum(p["unavailable"] for p in providers),
        },
        "flood_ratio_threshold": _FLOOD_RATIO_THRESHOLD,
        "rate_limiter_storage": _limiter_storage_status(),
        # Operator visibility for the Celery gate: while False, every `.delay()`
        # call site runs its work inline instead of queueing into a broker with
        # no consumer. Readable without shelling into the container.
        "celery_worker_enabled": _celery_settings.celery_worker_enabled,
    }
