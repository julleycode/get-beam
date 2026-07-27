"""Admin-only read API over the captured request/response log.

Three endpoints, all gated by ``require_admin``:
  GET /                  paginated list, faceted by reason/status/site/path
  GET /stats             counts per reason + per status class, for the header row
  GET /{log_id}          one row with full redacted bodies

Read-only by design. There is no delete endpoint — retention is enforced by the
7-day purge sweep, and a manual delete would only create a way to destroy the
audit trail of a rejection.
"""

from datetime import datetime, timedelta, timezone
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.config import settings
from apps.api.dependencies import require_admin
from apps.api.models.database import get_db
from apps.api.models.request_log import RequestLog
from apps.api.models.user import User

logger = structlog.get_logger()

router = APIRouter()

# Hard ceiling on page size. The bodies are JSONB blobs, so a large page is a
# large transfer — the UI pages instead.
_MAX_LIMIT = 200


def _serialize(row: RequestLog, *, include_bodies: bool) -> dict[str, Any]:
    """Shape one row for the client.

    The list view omits bodies entirely (``include_bodies=False``): they are the
    bulk of the payload and the operator only needs them once they have picked a
    row. The detail view returns everything.
    """
    base: dict[str, Any] = {
        "id": str(row.id),
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "method": row.method,
        "path": row.path,
        "status_code": row.status_code,
        "duration_ms": row.duration_ms,
        "reason": row.reason,
        "reason_detail": row.reason_detail,
        "site_id": row.site_id,
        "client_ip": row.client_ip,
        "user_agent": row.user_agent,
        "truncated": row.truncated,
    }
    if include_bodies:
        base |= {
            "query_params": row.query_params,
            "request_headers": row.request_headers,
            "request_body": row.request_body,
            "response_body": row.response_body,
            "user_id": str(row.user_id) if row.user_id else None,
        }
    return base


@router.get("")
async def list_request_logs(
    reason: str | None = Query(None, description="Filter by reason code"),
    site_id: str | None = Query(None),
    status_code: int | None = Query(None),
    path_contains: str | None = Query(None),
    hours: int = Query(24, ge=1, le=24 * 30, description="Look-back window"),
    limit: int = Query(50, ge=1, le=_MAX_LIMIT),
    offset: int = Query(0, ge=0),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Newest-first page of captured requests, with the active filters echoed back."""
    since = datetime.now(timezone.utc) - timedelta(hours=hours)

    conditions = [RequestLog.created_at >= since]
    if reason:
        conditions.append(RequestLog.reason == reason)
    if site_id:
        conditions.append(RequestLog.site_id == site_id)
    if status_code is not None:
        conditions.append(RequestLog.status_code == status_code)
    if path_contains:
        conditions.append(RequestLog.path.ilike(f"%{path_contains}%"))

    total = await db.scalar(
        select(func.count()).select_from(RequestLog).where(*conditions)
    )

    result = await db.execute(
        select(RequestLog)
        .where(*conditions)
        .order_by(RequestLog.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    rows = result.scalars().all()

    return {
        "enabled": settings.request_log_enabled,
        "retention_days": settings.request_log_retention_days,
        "total": total or 0,
        "limit": limit,
        "offset": offset,
        "logs": [_serialize(r, include_bodies=False) for r in rows],
    }


@router.get("/stats")
async def request_log_stats(
    hours: int = Query(24, ge=1, le=24 * 30),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Counts per reason and per status class over the window.

    Also reports ``enabled`` so the UI can tell "no traffic matched" apart from
    "capture is switched off" — otherwise both render as an empty table.
    """
    since = datetime.now(timezone.utc) - timedelta(hours=hours)

    reason_rows = await db.execute(
        select(RequestLog.reason, func.count())
        .where(RequestLog.created_at >= since)
        .group_by(RequestLog.reason)
        .order_by(func.count().desc())
    )
    status_rows = await db.execute(
        select(RequestLog.status_code, func.count())
        .where(RequestLog.created_at >= since)
        .group_by(RequestLog.status_code)
        .order_by(func.count().desc())
    )
    site_rows = await db.execute(
        select(RequestLog.site_id, func.count())
        .where(RequestLog.created_at >= since, RequestLog.site_id.isnot(None))
        .group_by(RequestLog.site_id)
        .order_by(func.count().desc())
        .limit(20)
    )

    by_reason = [{"reason": r, "count": c} for r, c in reason_rows.all()]
    return {
        "enabled": settings.request_log_enabled,
        "retention_days": settings.request_log_retention_days,
        "sample_rate": settings.request_log_sample_rate,
        "window_hours": hours,
        "total": sum(item["count"] for item in by_reason),
        "by_reason": by_reason,
        "by_status": [{"status_code": s, "count": c} for s, c in status_rows.all()],
        "by_site": [{"site_id": s, "count": c} for s, c in site_rows.all()],
    }


@router.get("/{log_id}")
async def get_request_log(
    log_id: str,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """One captured request with its full (redacted) request and response bodies."""
    try:
        import uuid as _uuid

        parsed = _uuid.UUID(log_id)
    except (ValueError, AttributeError):
        raise HTTPException(status_code=404, detail="Log not found")

    row = await db.get(RequestLog, parsed)
    if row is None:
        raise HTTPException(status_code=404, detail="Log not found")
    return _serialize(row, include_bodies=True)
