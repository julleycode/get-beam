"""Feature requests — public submit, owner-only listing + status management."""

import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.dependencies import get_current_user
from apps.api.models.database import get_db
from apps.api.models.feature_request import FeatureRequest
from apps.api.models.user import User
from apps.api.schemas.feature_requests import (
    FeatureRequestCreate,
    FeatureRequestListResponse,
    FeatureRequestOut,
    FeatureRequestUpdate,
)
from apps.api.services.email_sender import EmailSender

logger = structlog.get_logger()

router = APIRouter(tags=["feature-requests"])

_ALLOWED_URGENCY = {"nice", "useful", "critical"}
_ALLOWED_STATUS = {"new", "planned", "shipped", "closed"}

_URGENCY_LABEL = {
    "nice": "Nice to have",
    "useful": "Would use it",
    "critical": "Would pay for it",
}

_STATUS_LABEL = {
    "new": "New",
    "planned": "Planned",
    "shipped": "Shipped",
    "closed": "Closed",
}

_email_sender = EmailSender()


async def _notify_admin_new_request(req: FeatureRequest) -> None:
    """Send email to admin when a new feature request is submitted."""
    urgency_text = _URGENCY_LABEL.get(req.urgency or "", req.urgency or "Not specified")
    try:
        await _email_sender.send(
            to_email="tranthai.work@gmail.com",
            subject=f"New feature request: {req.title}",
            body_html=f"""
<h2 style="margin:0 0 16px 0;font-family:serif;">New Feature Request</h2>
<table style="border-collapse:collapse;width:100%;max-width:500px;">
  <tr><td style="padding:8px 12px;color:#666;width:100px;">Title</td><td style="padding:8px 12px;font-weight:600;">{req.title}</td></tr>
  <tr><td style="padding:8px 12px;color:#666;">Urgency</td><td style="padding:8px 12px;">{urgency_text}</td></tr>
  <tr><td style="padding:8px 12px;color:#666;">Email</td><td style="padding:8px 12px;">{req.email or "Not provided"}</td></tr>
  <tr><td style="padding:8px 12px;color:#666;">Detail</td><td style="padding:8px 12px;">{req.detail or "—"}</td></tr>
</table>
<br/>
<p style="font-size:13px;color:#999;">View all requests in your <a href="https://getbeam.fyi/dashboard/feature-requests">dashboard</a>.</p>
""",
            from_name="Beam Notifications",
        )
    except Exception:
        logger.warning("admin_notification_failed", request_id=str(req.id))


async def _notify_requester_status_change(
    req: FeatureRequest, old_status: str, new_status: str
) -> None:
    """Send email to the requester when their request status changes."""
    if not req.email:
        return

    new_label = _STATUS_LABEL.get(new_status, new_status)
    note_html = ""
    if req.admin_note:
        note_html = f'<p style="margin:16px 0;padding:12px 16px;background:#f5f5f5;border-radius:8px;font-size:14px;">{req.admin_note}</p>'

    status_color = {"planned": "#3b82f6", "shipped": "#22c55e", "closed": "#6b7280"}.get(new_status, "#666")

    try:
        await _email_sender.send(
            to_email=req.email,
            subject=f"Your feature request is now {new_label}: {req.title}",
            body_html=f"""
<h2 style="margin:0 0 8px 0;font-family:serif;">Feature Request Update</h2>
<p style="color:#666;margin:0 0 20px 0;">Your request has a new status.</p>
<table style="border-collapse:collapse;width:100%;max-width:500px;">
  <tr><td style="padding:8px 12px;color:#666;width:100px;">Request</td><td style="padding:8px 12px;font-weight:600;">{req.title}</td></tr>
  <tr><td style="padding:8px 12px;color:#666;">Status</td><td style="padding:8px 12px;"><span style="color:{status_color};font-weight:600;">{new_label}</span></td></tr>
</table>
{note_html}
<p style="margin-top:24px;font-size:13px;color:#999;">Thanks for helping us build a better product.</p>
""",
            from_name="Beam",
        )
    except Exception:
        logger.warning("requester_notification_failed", request_id=str(req.id), email=req.email)


@router.post("", response_model=FeatureRequestOut, status_code=201)
async def create_feature_request(
    body: FeatureRequestCreate,
    db: AsyncSession = Depends(get_db),
) -> FeatureRequestOut:
    """Public endpoint — anyone on the landing page can submit a feature request."""
    title = body.title.strip()
    if not title:
        raise HTTPException(status_code=422, detail="Title is required.")

    urgency = body.urgency if body.urgency in _ALLOWED_URGENCY else None
    email = (body.email or "").strip() or None

    req = FeatureRequest(
        id=uuid.uuid4(),
        title=title[:120],
        detail=(body.detail or "").strip() or None,
        urgency=urgency,
        email=email,
        source="landing_fab",
        status="new",
    )
    db.add(req)
    await db.commit()
    await db.refresh(req)

    logger.info("feature_request_created", id=str(req.id), urgency=urgency, has_email=bool(email))

    await _notify_admin_new_request(req)

    return FeatureRequestOut.model_validate(req)


@router.get("", response_model=FeatureRequestListResponse)
async def list_feature_requests(
    status: str | None = Query(None, description="Filter by status: new / planned / shipped / closed"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> FeatureRequestListResponse:
    """Owner-only — view submitted feature requests (auth required)."""
    query = select(FeatureRequest)
    count_query = select(func.count()).select_from(FeatureRequest)
    if status:
        query = query.where(FeatureRequest.status == status)
        count_query = count_query.where(FeatureRequest.status == status)

    total = (await db.execute(count_query)).scalar() or 0
    query = query.order_by(desc(FeatureRequest.created_at)).offset((page - 1) * page_size).limit(page_size)
    rows = (await db.execute(query)).scalars().all()

    return FeatureRequestListResponse(
        requests=[FeatureRequestOut.model_validate(r) for r in rows],
        total=total,
    )


@router.patch("/{request_id}", response_model=FeatureRequestOut)
async def update_feature_request(
    request_id: uuid.UUID,
    body: FeatureRequestUpdate,
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> FeatureRequestOut:
    """Owner-only — update status and/or admin note on a feature request."""
    result = await db.execute(select(FeatureRequest).where(FeatureRequest.id == request_id))
    req = result.scalar_one_or_none()
    if not req:
        raise HTTPException(status_code=404, detail="Feature request not found.")

    old_status = req.status
    status_changed = False

    if body.status is not None:
        if body.status not in _ALLOWED_STATUS:
            raise HTTPException(status_code=422, detail=f"Invalid status. Must be one of: {', '.join(sorted(_ALLOWED_STATUS))}")
        if body.status != old_status:
            req.status = body.status
            status_changed = True

    if body.admin_note is not None:
        req.admin_note = body.admin_note.strip() or None

    await db.commit()
    await db.refresh(req)

    logger.info(
        "feature_request_updated",
        id=str(req.id),
        old_status=old_status,
        new_status=req.status,
        has_note=bool(req.admin_note),
    )

    if status_changed:
        await _notify_requester_status_change(req, old_status, req.status)

    return FeatureRequestOut.model_validate(req)
