from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.models.campaign import Campaign, CampaignTouchpoint
from apps.api.models.database import get_db
from apps.api.models.event import Event
from apps.api.models.segment import Segment, SegmentMember
from apps.api.models.social_account import SocialAccount
from apps.api.models.user import User
from apps.api.models.visitor import IdentifiedVisitor, Visitor
from apps.api.dependencies import get_current_user, verify_site_access
from apps.api.schemas.campaigns import (
    CampaignListResponse,
    CampaignOut,
    CampaignStatsResponse,
    CampaignStatusUpdate,
    CampaignTestSendRequest,
    ReturnedVisitor,
)
from apps.api.agents.campaign_planner import plan_campaign
from apps.api.agents.segmenter import build_visitor_profiles
from apps.api.services.campaign_sender import (
    _first_email_touchpoint,
    _personalize,
    send_campaign_emails,
)
from apps.api.services.email_rate_limiter import check_and_reserve_email
from apps.api.services.email_sender import EmailSender
from apps.api.services.pii import mask_email

router = APIRouter()
logger = structlog.get_logger()

VALID_TRANSITIONS: dict[str, list[str]] = {
    "draft": ["approved"],
    "approved": ["active", "draft"],
    "active": ["paused", "completed"],
    "paused": ["active", "completed"],
}


@router.get("/{site_id}", response_model=CampaignListResponse)
async def list_campaigns(
    site_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CampaignListResponse:
    await verify_site_access(db, site_id, user)

    result = await db.execute(
        select(Campaign).where(Campaign.site_id == site_id).order_by(Campaign.created_at.desc())
    )
    campaigns = [CampaignOut.model_validate(c) for c in result.scalars().all()]
    return CampaignListResponse(campaigns=campaigns, total=len(campaigns))


@router.post("/{site_id}/create/{segment_id}", response_model=CampaignOut)
async def create_campaign_from_segment(
    site_id: str,
    segment_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CampaignOut:
    """Create a campaign plan from a segment using AI.

    Pulls enriched visitor profiles from the segment, checks for connected
    social accounts, and generates a multi-channel campaign plan that includes
    social outreach for visitors with known social handles.
    """
    await verify_site_access(db, site_id, user)

    seg_result = await db.execute(
        select(Segment).where(Segment.id == segment_id, Segment.site_id == site_id)
    )
    segment = seg_result.scalar_one_or_none()
    if not segment:
        raise HTTPException(status_code=404, detail="Segment not found")

    # Get visitor profiles in this segment
    members_result = await db.execute(
        select(SegmentMember.visitor_id).where(SegmentMember.segment_id == segment.id)
    )
    visitor_ids = [row[0] for row in members_result.all()]

    profiles: list[dict] = []
    if visitor_ids:
        visitors_result = await db.execute(
            select(Visitor).where(
                Visitor.site_id == site_id,
                Visitor.visitor_id.in_(visitor_ids),
            )
        )
        # Identity fields (email, name) live on IdentifiedVisitor and enrichment
        # fields (job, company, socials, recent content) on EnrichmentProfile —
        # NOT on Visitor. build_visitor_profiles joins all three correctly; it's
        # the same builder the auto-segmentation path uses.
        profiles = await build_visitor_profiles(
            db, site_id, list(visitors_result.scalars().all())
        )

    # Get connected social accounts for this user
    accts_result = await db.execute(
        select(SocialAccount).where(
            SocialAccount.user_id == user.id,
            SocialAccount.is_active.is_(True),
        )
    )
    connected = [
        {"platform": a.platform.value, "username": a.username}
        for a in accts_result.scalars().all()
    ]

    try:
        campaign = await plan_campaign(
            db=db,
            segment=segment,
            visitor_profiles=profiles,
            connected_accounts=connected,
        )
    except Exception:
        logger.exception("campaign_planning_failed", segment_id=segment_id)
        raise HTTPException(
            status_code=502,
            detail="Campaign planning failed — the AI service returned an error. Please try again.",
        )

    logger.info(
        "campaign_created",
        campaign_id=str(campaign.id),
        segment_id=segment_id,
        has_social_channels=any(
            tp.get("channel") in ("social_reply", "social_dm")
            for tp in campaign.plan.get("touchpoints", [])
        ),
    )
    return CampaignOut.model_validate(campaign)


@router.get("/{site_id}/{campaign_id}", response_model=CampaignOut)
async def get_campaign(
    site_id: str,
    campaign_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CampaignOut:
    await verify_site_access(db, site_id, user)

    result = await db.execute(
        select(Campaign).where(Campaign.id == campaign_id, Campaign.site_id == site_id)
    )
    campaign = result.scalar_one_or_none()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return CampaignOut.model_validate(campaign)


@router.get("/{site_id}/{campaign_id}/stats", response_model=CampaignStatsResponse)
async def get_campaign_stats(
    site_id: str,
    campaign_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CampaignStatsResponse:
    """Email engagement stats + the identified recipients who returned to the
    site after the send.

    Open counts OVERCOUNT under Apple Mail Privacy Protection (proxy prefetch)
    and undercount when images are blocked — clicks and return visits are the
    honest signals. "Returned" = a pageview by the recipient's visitor_id after
    their email's sent_at (same-device attribution; a click from a brand-new
    device still stamps clicked_at via _tp but may not appear as returned).
    """
    await verify_site_access(db, site_id, user)

    result = await db.execute(
        select(Campaign).where(Campaign.id == campaign_id, Campaign.site_id == site_id)
    )
    campaign = result.scalar_one_or_none()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    tp_rows = (
        (
            await db.execute(
                select(CampaignTouchpoint).where(
                    CampaignTouchpoint.campaign_id == campaign.id,
                    CampaignTouchpoint.channel == "email",
                    CampaignTouchpoint.status == "sent",
                )
            )
        )
        .scalars()
        .all()
    )

    sent = len(tp_rows)
    opened = sum(1 for t in tp_rows if t.opened_at is not None)
    clicked = sum(1 for t in tp_rows if t.clicked_at is not None)

    returned: list[ReturnedVisitor] = []
    if tp_rows:
        # Return visits: pageviews by a recipient AFTER their own email went out.
        # Joined on the touchpoint so each visitor uses their own sent_at cutoff;
        # hits ix_events_site_visitor, scans only recipient rows.
        visit_rows = (
            await db.execute(
                select(
                    Event.visitor_id,
                    func.max(Event.created_at).label("last_visit"),
                    func.count().label("pageviews"),
                )
                .join(
                    CampaignTouchpoint,
                    and_(
                        CampaignTouchpoint.visitor_id == Event.visitor_id,
                        CampaignTouchpoint.campaign_id == campaign.id,
                        CampaignTouchpoint.channel == "email",
                        CampaignTouchpoint.status == "sent",
                    ),
                )
                .where(
                    Event.site_id == site_id,
                    Event.event_type == "pageview",
                    Event.created_at > CampaignTouchpoint.sent_at,
                )
                .group_by(Event.visitor_id)
                .order_by(func.max(Event.created_at).desc())
                .limit(100)
            )
        ).all()

        if visit_rows:
            tp_by_visitor = {t.visitor_id: t for t in tp_rows}
            iv_rows = (
                (
                    await db.execute(
                        select(IdentifiedVisitor).where(
                            IdentifiedVisitor.site_id == site_id,
                            IdentifiedVisitor.visitor_id.in_(
                                [r.visitor_id for r in visit_rows]
                            ),
                        )
                    )
                )
                .scalars()
                .all()
            )
            iv_by_visitor = {iv.visitor_id: iv for iv in iv_rows}
            for r in visit_rows:
                tp = tp_by_visitor.get(r.visitor_id)
                iv = iv_by_visitor.get(r.visitor_id)
                returned.append(
                    ReturnedVisitor(
                        visitor_id=r.visitor_id,
                        full_name=iv.full_name if iv else None,
                        email_masked=mask_email(iv.email) if iv and iv.email else None,
                        opened_at=tp.opened_at if tp else None,
                        clicked_at=tp.clicked_at if tp else None,
                        last_visit_at=r.last_visit,
                        pageviews_after=int(r.pageviews),
                    )
                )

    return CampaignStatsResponse(
        sent=sent,
        opened=opened,
        clicked=clicked,
        open_rate=round(opened / sent, 4) if sent else 0.0,
        click_rate=round(clicked / sent, 4) if sent else 0.0,
        returned_visitors=returned,
    )


@router.patch("/{site_id}/{campaign_id}/status", response_model=CampaignOut)
async def update_campaign_status(
    site_id: str,
    campaign_id: str,
    body: CampaignStatusUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CampaignOut:
    await verify_site_access(db, site_id, user)

    result = await db.execute(
        select(Campaign).where(Campaign.id == campaign_id, Campaign.site_id == site_id)
    )
    campaign = result.scalar_one_or_none()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    allowed = VALID_TRANSITIONS.get(campaign.status, [])
    if body.status not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot transition from '{campaign.status}' to '{body.status}'",
        )

    campaign.status = body.status
    # Naive UTC: Campaign datetime columns are TIMESTAMP WITHOUT TIME ZONE;
    # asyncpg rejects tz-aware values for them (same pattern as
    # visitor_aggregator). Do not pass datetime.now(timezone.utc) directly.
    if body.status == "approved":
        campaign.approved_at = datetime.now(timezone.utc).replace(tzinfo=None)
    elif body.status == "active":
        campaign.started_at = datetime.now(timezone.utc).replace(tzinfo=None)

    await db.commit()
    await db.refresh(campaign)
    return CampaignOut.model_validate(campaign)


@router.post("/{site_id}/{campaign_id}/test-send")
async def test_send_campaign(
    site_id: str,
    campaign_id: str,
    body: CampaignTestSendRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Send a [TEST]-prefixed preview of the campaign's first email touchpoint
    to an admin-entered address.

    Allowed in any campaign status; never mutates the campaign, never writes a
    CampaignTouchpoint. Personalizes with a sample name (no real recipient PII).
    Counts against the per-site hourly cap so this can't be abused as a relay.
    """
    await verify_site_access(db, site_id, user)

    result = await db.execute(
        select(Campaign).where(Campaign.id == campaign_id, Campaign.site_id == site_id)
    )
    campaign = result.scalar_one_or_none()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    touchpoint = _first_email_touchpoint(campaign.plan or {})
    if touchpoint is None:
        raise HTTPException(status_code=400, detail="Campaign has no email touchpoint to test")

    if not await check_and_reserve_email(site_id):
        raise HTTPException(
            status_code=429,
            detail="Hourly email cap reached for this site — try again later",
        )

    subject = "[TEST] " + _personalize(touchpoint["subject"], "Alex Example")
    # Links are NOT click-decorated here: a test click must not create
    # VisitorEmail rows or tracking state for the admin's own address.
    body_html = _personalize(touchpoint["body"], "Alex Example").replace("\n", "<br/>")

    sender = EmailSender()
    try:
        send_result = await sender.send(
            to_email=body.email,
            subject=subject,
            body_html=body_html,
            db=db,
        )
    except Exception:
        logger.exception("campaign_test_send_failed", campaign_id=str(campaign.id))
        raise HTTPException(status_code=502, detail="Test email failed to send")

    if send_result is None:
        raise HTTPException(
            status_code=400,
            detail="This address is unsubscribed/suppressed and cannot receive email",
        )

    logger.info("campaign_test_sent", campaign_id=str(campaign.id), to=mask_email(body.email))
    return {"sent": True, "to": mask_email(body.email)}


@router.post("/{site_id}/{campaign_id}/start")
async def start_campaign(
    site_id: str,
    campaign_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """One-click launch ("Start beam"): approve + activate + send in one action.

    The dashboard's confirm dialog is the deliberate human-approval gate that
    used to be the separate draft->approved step. Sending reuses
    send_campaign_emails with all its guardrails (suppression, do_not_email,
    hourly cap, per-recipient idempotency), so re-invoking on an active
    campaign only reaches segment members not yet emailed.
    """
    await verify_site_access(db, site_id, user)

    result = await db.execute(
        select(Campaign).where(Campaign.id == campaign_id, Campaign.site_id == site_id)
    )
    campaign = result.scalar_one_or_none()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    if campaign.status == "completed":
        raise HTTPException(status_code=409, detail="Campaign is already completed")

    is_email = campaign.campaign_type == "email"
    # Validate sendability BEFORE mutating status so a doomed start leaves the
    # campaign untouched instead of half-activated.
    if is_email:
        if _first_email_touchpoint(campaign.plan or {}) is None:
            raise HTTPException(status_code=400, detail="Campaign has no email touchpoint to send")
        if campaign.segment_id is None:
            raise HTTPException(status_code=400, detail="Campaign has no segment audience")

    # Naive UTC — same TIMESTAMP WITHOUT TIME ZONE constraint as update_campaign_status.
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    if campaign.status == "draft":
        campaign.approved_at = now
    if campaign.status in ("draft", "approved", "paused"):
        campaign.status = "active"
    if campaign.started_at is None:
        campaign.started_at = now
    await db.commit()
    await db.refresh(campaign)

    summary = {
        "total_audience": 0,
        "sent": 0,
        "skipped_no_email": 0,
        "skipped_suppressed": 0,
        "skipped_company_level": 0,
        "skipped_already_sent": 0,
        "throttled": 0,
        "failed": 0,
    }
    if is_email:
        try:
            summary = await send_campaign_emails(db, campaign)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        # Same completion rule as the legacy send endpoint.
        if summary["throttled"] == 0 and summary["sent"] > 0:
            campaign.status = "completed"
            await db.commit()

    logger.info(
        "campaign_started",
        campaign_id=str(campaign.id),
        campaign_type=campaign.campaign_type,
        status=campaign.status,
        sent=summary["sent"],
        throttled=summary["throttled"],
        failed=summary["failed"],
    )
    return {"campaign_id": str(campaign.id), "status": campaign.status, "summary": summary}


@router.post("/{site_id}/{campaign_id}/send")
async def send_campaign(
    site_id: str,
    campaign_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Send the campaign's email touchpoint to its segment audience.

    Requires the campaign to be ACTIVE — the explicit human-approval gate, since
    a campaign only reaches 'active' via a deliberate user-driven status change.
    The send path skips do_not_email recipients, honors the per-site hourly cap,
    injects a signed unsubscribe link (via EmailSender), and is idempotent per
    recipient so re-invoking never double-sends.
    """
    await verify_site_access(db, site_id, user)

    result = await db.execute(
        select(Campaign).where(Campaign.id == campaign_id, Campaign.site_id == site_id)
    )
    campaign = result.scalar_one_or_none()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    if campaign.status != "active":
        raise HTTPException(
            status_code=400,
            detail="Campaign must be 'active' to send. Approve and activate it first.",
        )

    try:
        summary = await send_campaign_emails(db, campaign)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Mark completed once the full audience was processed without hitting the cap.
    if summary["throttled"] == 0 and summary["sent"] > 0:
        campaign.status = "completed"
        await db.commit()

    logger.info(
        "campaign_sent",
        campaign_id=str(campaign.id),
        sent=summary["sent"],
        suppressed=summary["skipped_suppressed"],
        throttled=summary["throttled"],
        failed=summary["failed"],
    )
    return {"campaign_id": str(campaign.id), "status": campaign.status, "summary": summary}
