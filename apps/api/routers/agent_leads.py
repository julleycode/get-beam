"""Owner-facing, authenticated list of WS3 agent-concierge leads.

``GET /api/v1/agent-leads/{site_id}`` — Clerk-authenticated, tenant-scoped via
the shared ``verify_site_access`` (404 on unknown or foreign site ids, never
403). Lets an owner see every lead even when the daily email budget was spent or
the notification email failed.

Read-only. The stored network prefix (``ip_address``) is deliberately not
returned; owners get the qualification fields, best-effort company domain,
and whether an email went out.
"""

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.dependencies import get_current_user, verify_site_access
from apps.api.models.agent_lead import AgentLead
from apps.api.models.database import get_db
from apps.api.models.user import User

router = APIRouter()


class AgentLeadItem(BaseModel):
    id: UUID
    created_at: datetime
    tool_name: str
    use_case: str | None
    company_size: str | None
    evaluating_against: str | None
    resolved_company_domain: str | None
    notified: bool


class AgentLeadListResponse(BaseModel):
    leads: list[AgentLeadItem]


@router.get("/{site_id}", response_model=AgentLeadListResponse)
async def list_agent_leads(
    site_id: str,
    limit: int = Query(default=50, ge=1, le=200),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AgentLeadListResponse:
    await verify_site_access(db, site_id, user)
    rows = (
        await db.execute(
            select(AgentLead)
            .where(AgentLead.site_id == site_id)
            .order_by(AgentLead.created_at.desc())
            .limit(limit)
        )
    ).scalars().all()
    return AgentLeadListResponse(
        leads=[
            AgentLeadItem(
                id=r.id,
                created_at=r.created_at,
                tool_name=r.tool_name,
                use_case=r.use_case,
                company_size=r.company_size,
                evaluating_against=r.evaluating_against,
                resolved_company_domain=r.resolved_company_domain,
                notified=bool(r.notified),
            )
            for r in rows
        ]
    )
