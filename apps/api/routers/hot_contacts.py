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
