"""Companies router — list companies identified from visitor IPs."""

import structlog
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.models.company import Company
from apps.api.models.database import get_db
from apps.api.models.site import Site
from apps.api.models.user import User
from apps.api.dependencies import get_current_user

router = APIRouter()
logger = structlog.get_logger()


async def _verify_site_access(
    site_id: str,
    user: User,
    db: AsyncSession,
) -> Site:
    """Return the Site if it exists and belongs to the current user; raise 404 otherwise."""
    result = await db.execute(
        select(Site).where(Site.site_id == site_id, Site.user_id == user.id)
    )
    site = result.scalar_one_or_none()
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")
    return site


@router.get("/{site_id}")
async def list_companies(
    site_id: str,
    page: int = 1,
    page_size: int = 50,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """List companies identified for a site, ordered by intent score."""
    await _verify_site_access(site_id, user, db)

    offset = (page - 1) * page_size

    total_q = await db.execute(
        select(func.count()).select_from(Company).where(Company.site_id == site_id)
    )
    total = total_q.scalar() or 0

    result = await db.execute(
        select(Company)
        .where(Company.site_id == site_id)
        .order_by(Company.intent_score.desc(), Company.last_seen.desc())
        .offset(offset)
        .limit(page_size)
    )
    companies = result.scalars().all()

    return {
        "companies": [
            {
                "id": str(c.id),
                "domain": c.domain,
                "name": c.name,
                "industry": c.industry,
                "employee_count": c.employee_count,
                "city": c.city,
                "country": c.country,
                "total_visitors": c.total_visitors,
                "total_sessions": c.total_sessions,
                "total_pageviews": c.total_pageviews,
                "intent_score": c.intent_score,
                "first_seen": c.first_seen.isoformat() if c.first_seen else None,
                "last_seen": c.last_seen.isoformat() if c.last_seen else None,
            }
            for c in companies
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }
