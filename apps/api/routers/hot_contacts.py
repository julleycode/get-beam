"""Hot imported contacts (identity-honesty Phase 6) — read-only dashboard feed.

DELIBERATELY A SEPARATE ROUTER FILE from ``routers/contacts.py`` (Phase 4).
That file already registers ``GET /{site_id}/contacts/{visitor_id}``; a
``/{site_id}/contacts/hot`` route appended AFTER it would never be reached —
FastAPI matches in registration order, so every request would be swallowed by
``get_imported_contact`` with ``visitor_id="hot"`` and silently 404, with no
import-time or unit-test signal. Keeping this in its own module, included in
``main.py`` BEFORE ``contacts.router``, makes the ordering explicit and
auditable instead of load-bearing on where a function sits inside a 200-line
file.

Also deliberately NOT part of ``routers/dashboard.py``'s ``get_overview()``
aggregate (Phase 1's owned surface) — this is a genuinely separate query.
"""

import structlog
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.dependencies import get_current_user, verify_site_access
from apps.api.models.database import get_db
from apps.api.models.user import User
from apps.api.services.hot_contacts import (
    DEFAULT_ACTIVITY_WINDOW_DAYS,
    MAX_HOT_CONTACTS_RETURNED,
    MAX_JOB_CHANGES_RETURNED,
    get_job_change_events,
    hot_contacts_summary,
)

logger = structlog.get_logger()

router = APIRouter()


class HotContact(BaseModel):
    visitor_id: str
    email: str | None
    full_name: str | None
    last_activity_at: str | None


class HotContactsSummary(BaseModel):
    """"N of your M imported contacts active this week."""

    active_count: int
    total_count: int
    window_days: int
    contacts: list[HotContact]


@router.get("/{site_id}/contacts/hot", response_model=HotContactsSummary)
async def get_hot_imported_contacts(
    site_id: str,
    days: int = Query(DEFAULT_ACTIVITY_WINDOW_DAYS, ge=1, le=90),
    limit: int = Query(MAX_HOT_CONTACTS_RETURNED, ge=1, le=MAX_HOT_CONTACTS_RETURNED),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> HotContactsSummary:
    """Imported contacts with real activity in the last ``days`` days.

    Site ownership goes through the shared ``verify_site_access`` dependency
    (404, never 403 — never leak which site_ids exist), matching every sibling
    site-scoped router.
    """
    await verify_site_access(db, site_id, user)
    summary = await hot_contacts_summary(db, site_id, days=days, limit=limit)
    return HotContactsSummary(
        active_count=summary["active_count"],
        total_count=summary["total_count"],
        window_days=summary["window_days"],
        contacts=[
            HotContact(
                visitor_id=c["visitor_id"],
                email=c["email"],
                full_name=c["full_name"],
                last_activity_at=(
                    c["last_activity_at"].isoformat() if c["last_activity_at"] else None
                ),
            )
            for c in summary["contacts"]
        ],
    )


class JobChangeEventOut(BaseModel):
    """One confirmed employer change. Carries NO email/name (SPEC AC-14) —
    the person is referenced by visitor_id, which the Visitors surface resolves."""

    visitor_id: str
    prior_company: str | None
    new_company: str | None
    prior_job_title: str | None
    new_job_title: str | None
    confidence: float
    corroboration_signal: str | None
    detected_at: str | None


class JobChangeFeed(BaseModel):
    events: list[JobChangeEventOut]
    count: int


# ROUTE-ORDER SAFE (checked against this module's own docstring warning):
# "/{site_id}/job-changes" has a LITERAL second segment. The only parametric
# second-segment route registered at the /api/v1/sites prefix is sites.py's
# "/{site_id}", which is one segment shorter and cannot match; contacts.py's
# catch-all is "/{site_id}/contacts/{visitor_id}", three segments deep. So
# nothing swallows this route and this route swallows nothing.
@router.get("/{site_id}/job-changes", response_model=JobChangeFeed)
async def get_job_changes(
    site_id: str,
    limit: int = Query(MAX_JOB_CHANGES_RETURNED, ge=1, le=MAX_JOB_CHANGES_RETURNED),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JobChangeFeed:
    """Recently detected job changes for a site (newest first).

    Read-only. Site ownership goes through the same shared ``verify_site_access``
    dependency as every sibling site-scoped route (404, never 403 — never leak
    which site_ids exist). Empty while job-change detection is disabled.
    """
    await verify_site_access(db, site_id, user)
    events = await get_job_change_events(db, site_id, limit=limit)
    return JobChangeFeed(
        count=len(events),
        events=[
            JobChangeEventOut(
                visitor_id=e.visitor_id,
                prior_company=e.prior_company,
                new_company=e.new_company,
                prior_job_title=e.prior_job_title,
                new_job_title=e.new_job_title,
                confidence=e.confidence,
                corroboration_signal=e.corroboration_signal,
                detected_at=e.detected_at.isoformat() if e.detected_at else None,
            )
            for e in events
        ],
    )
