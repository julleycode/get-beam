"""Companies router — list companies identified from visitor IPs."""

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.models.company import Company
from apps.api.models.database import get_db
from apps.api.models.site import Site
from apps.api.models.user import User
from apps.api.dependencies import get_current_user, verify_site_access

router = APIRouter()
logger = structlog.get_logger()


@router.get("/{site_id}")
async def list_companies(
    site_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """List companies identified for a site, ordered by intent score."""
    await verify_site_access(db, site_id, user)

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
