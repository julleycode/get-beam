from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import and_, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.models.campaign import Campaign, CampaignTouchpoint
from apps.api.models.database import get_db
from apps.api.models.enrichment import EnrichmentProfile
from apps.api.models.event import Event
from apps.api.models.segment import Segment, SegmentMember
from apps.api.models.social_account import Platform, SocialAccount
from apps.api.models.user import User
from apps.api.models.visitor import IdentifiedVisitor, Visitor
from apps.api.config import settings
from apps.api.dependencies import get_current_user, verify_site_access
from apps.api.schemas.campaigns import (
    MAX_LINKEDIN_OUTREACH_LIMIT,
    CampaignListResponse,
    CampaignOut,
    CampaignStatsResponse,
    CampaignStatusUpdate,
    CampaignTestSendRequest,
    LinkedInCampaignDetailResponse,
    LinkedInOutreachJobResponse,
    LinkedInOutreachRequest,
    LinkedInOutreachResponse,
    LinkedInScheduleRequest,
    LinkedInScheduleResponse,
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
from apps.api.services.identity_classification import (
    is_emailable_identity,
    is_graph_candidate_provider,
    is_verified_identity,
)
from apps.api.services.phantommm_client import (
    PhantommmClient,
    PhantommmError,
    PhantommmNotConfigured,
)
from apps.api.services.pii import mask_email
from apps.api.services.suppression import is_email_suppressed

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
    include_archived: bool = False,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CampaignListResponse:
    await verify_site_access(db, site_id, user)

    query = select(Campaign).where(Campaign.site_id == site_id)
    if not include_archived:
        query = query.where(Campaign.status != "archived")
    query = query.order_by(Campaign.created_at.desc())

    result = await db.execute(query)
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

    # Conversion outcomes for this campaign (lifetime, matching the counters
    # above). Distinct visitors so one buyer hitting a repeatable goal twice
    # still counts as one converted person.
    from apps.api.models.outcome import Conversion

    conv_row = (
        await db.execute(
            select(
                func.count(func.distinct(Conversion.visitor_id)),
                func.coalesce(func.sum(Conversion.value_cents), 0),
            ).where(Conversion.campaign_id == campaign.id)
        )
    ).one()
    converted = int(conv_row[0] or 0)
    revenue_cents = int(conv_row[1] or 0)

    return CampaignStatsResponse(
        sent=sent,
        opened=opened,
        clicked=clicked,
        open_rate=round(opened / sent, 4) if sent else 0.0,
        click_rate=round(clicked / sent, 4) if sent else 0.0,
        converted=converted,
        conversion_rate=round(converted / sent, 4) if sent else 0.0,
        revenue_cents=revenue_cents,
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


async def _get_campaign_or_404(
    db: AsyncSession, site_id: str, campaign_id: str
) -> Campaign:
    result = await db.execute(
        select(Campaign).where(Campaign.id == campaign_id, Campaign.site_id == site_id)
    )
    campaign = result.scalar_one_or_none()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return campaign


@router.post("/{site_id}/{campaign_id}/archive", response_model=CampaignOut)
async def archive_campaign(
    site_id: str,
    campaign_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CampaignOut:
    """Hide a campaign from the default list without deleting it. Reversible
    via /unarchive. Allowed from any status."""
    await verify_site_access(db, site_id, user)
    campaign = await _get_campaign_or_404(db, site_id, campaign_id)

    campaign.status = "archived"
    await db.commit()
    await db.refresh(campaign)
    logger.info("campaign_archived", site_id=site_id, campaign_id=campaign_id)
    return CampaignOut.model_validate(campaign)


@router.post("/{site_id}/{campaign_id}/unarchive", response_model=CampaignOut)
async def unarchive_campaign(
    site_id: str,
    campaign_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CampaignOut:
    """Restore an archived campaign back to draft."""
    await verify_site_access(db, site_id, user)
    campaign = await _get_campaign_or_404(db, site_id, campaign_id)

    if campaign.status != "archived":
        raise HTTPException(status_code=400, detail="Campaign is not archived")

    campaign.status = "draft"
    await db.commit()
    await db.refresh(campaign)
    logger.info("campaign_unarchived", site_id=site_id, campaign_id=campaign_id)
    return CampaignOut.model_validate(campaign)


@router.delete("/{site_id}/{campaign_id}", status_code=204)
async def delete_campaign(
    site_id: str,
    campaign_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Permanently delete a campaign and its touchpoints (open/click history)."""
    await verify_site_access(db, site_id, user)
    campaign = await _get_campaign_or_404(db, site_id, campaign_id)

    await db.execute(
        delete(CampaignTouchpoint).where(CampaignTouchpoint.campaign_id == campaign.id)
    )
    await db.delete(campaign)
    await db.commit()
    logger.info("campaign_deleted", site_id=site_id, campaign_id=campaign_id)


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

    # From-name = the site's own name; Reply-To = the admin's address (this is a
    # preview to themselves). Mirrors the real send in campaign_sender.
    from apps.api.models.site import Site

    # Two-column select — must use .first(), not .scalar_one_or_none() (which
    # raises on a multi-column row). booking_url feeds {{booking_link}} so the
    # preview renders exactly what a real send would.
    site_row = (
        await db.execute(
            select(Site.name, Site.booking_url).where(Site.site_id == site_id)
        )
    ).first()
    site_name = (site_row[0] if site_row else None) or "Beam"
    booking_url = (site_row[1] if site_row else None) or None

    # Sample recipient values so the preview renders fully (no raw
    # {{placeholders}}); [Your Name] resolves to the admin running the test.
    sample_name = "Alex Example"
    sample_company = "Acme Inc"
    sender_name = user.full_name or None
    subject = "[TEST] " + _personalize(
        touchpoint["subject"], sample_name, sample_company, sender_name, booking_url
    )
    # Links are NOT click-decorated here: a test click must not create
    # VisitorEmail rows or tracking state for the admin's own address.
    body_html = _personalize(
        touchpoint["body"], sample_name, sample_company, sender_name, booking_url
    ).replace("\n", "<br/>")

    # Preview through the SAME channel a real send would use: the owner's
    # connected Gmail if present, otherwise Beam/SendGrid.
    from apps.api.services.email_providers.gmail_sender import (
        resolve_sender_for_site,
        send_via_gmail,
    )
    from apps.api.services.email_providers import gmail as gmail_client
    from apps.api.services.campaign_sender import _unsubscribe_footer

    gmail_sender = await resolve_sender_for_site(db, site_id)

    if gmail_sender is not None:
        if await is_email_suppressed(db, body.email, "do_not_email"):
            raise HTTPException(
                status_code=400,
                detail="This address is unsubscribed/suppressed and cannot receive email",
            )
        try:
            unsub_url, unsub_footer = _unsubscribe_footer(body.email)
            await send_via_gmail(
                db,
                gmail_sender,
                to_email=body.email,
                subject=subject,
                body_html=body_html + unsub_footer,
                unsubscribe_url=unsub_url,
            )
        except (gmail_client.GmailOAuthError, RuntimeError):
            logger.exception("campaign_test_send_gmail_failed", campaign_id=str(campaign.id))
            raise HTTPException(status_code=502, detail="Test email failed to send via Gmail")
        logger.info(
            "campaign_test_sent",
            campaign_id=str(campaign.id),
            to=mask_email(body.email),
            channel="gmail",
        )
        return {"sent": True, "to": mask_email(body.email), "channel": "gmail"}

    sender = EmailSender()
    try:
        send_result = await sender.send(
            to_email=body.email,
            subject=subject,
            body_html=body_html,
            from_name=site_name,
            reply_to=user.email,
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
    return {"sent": True, "to": mask_email(body.email), "channel": "beam"}


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


# ─── LinkedIn outreach (via phantommm sidecar) ───────────────────────────────


def _first_linkedin_touchpoint(plan: dict) -> dict | None:
    """Return the first LinkedIn touchpoint in the campaign plan, or None."""
    for tp in (plan or {}).get("touchpoints", []):
        if tp.get("channel") == "linkedin":
            return tp
    return None


async def _resolve_linkedin_targets(
    db: AsyncSession, site_id: str, campaign: Campaign, limit: int
) -> tuple[list[str], int]:
    """Resolve a campaign's segment audience to LinkedIn profile URLs.

    Walks the segment members, applies the same emailability/do_not_email/
    suppression guards the email send path uses, and collects each visitor's
    enriched LinkedIn URL (up to a hard server-side cap). Returns
    ``(urls, skipped_no_linkedin)``.

    Shared by both the immediate outreach and the scheduled-campaign endpoints
    so audience selection behaves identically for both.
    """
    member_rows = await db.execute(
        select(SegmentMember.visitor_id).where(
            SegmentMember.segment_id == campaign.segment_id
        )
    )
    visitor_ids = [r[0] for r in member_rows.all()]

    urls: list[str] = []
    skipped_no_linkedin = 0
    hard_limit = min(limit, MAX_LINKEDIN_OUTREACH_LIMIT)

    for vid in visitor_ids:
        if len(urls) >= hard_limit:
            break

        iv_row = await db.execute(
            select(IdentifiedVisitor).where(
                IdentifiedVisitor.site_id == site_id,
                IdentifiedVisitor.visitor_id == vid,
            )
        )
        iv = iv_row.scalar_one_or_none()
        # Skip do_not_contact (do_not_email covers unsubscribed/bounced) and
        # company-level guesses (same non-emailable guard the email path uses).
        if iv is not None:
            if iv.do_not_email:
                skipped_no_linkedin += 1
                continue
            contactable = is_emailable_identity(
                iv.resolution_provider,
                getattr(iv, "source_agent_visit_id", None),
                getattr(iv, "is_abuse_flagged", False),
            )
            # D5/D10 confirm-gate (see config.candidate_outreach_enabled). Only
            # queried for graph-candidate providers, so the common path is
            # unchanged. Additive-restrictive: can narrow, never widen.
            if (
                contactable
                and is_graph_candidate_provider(iv.resolution_provider)
                and not settings.candidate_outreach_enabled
            ):
                identity_status = (
                    await db.execute(
                        select(Visitor.identity_status).where(
                            Visitor.site_id == site_id,
                            Visitor.visitor_id == vid,
                        )
                    )
                ).scalar_one_or_none()
                contactable = is_verified_identity(identity_status)
            if not contactable:
                skipped_no_linkedin += 1
                continue
            if iv.email and await is_email_suppressed(db, iv.email, "do_not_email"):
                skipped_no_linkedin += 1
                continue

        linkedin_url = (
            await db.execute(
                select(EnrichmentProfile.linkedin_url).where(
                    EnrichmentProfile.site_id == site_id,
                    EnrichmentProfile.visitor_id == vid,
                )
            )
        ).scalar_one_or_none()

        if not linkedin_url:
            skipped_no_linkedin += 1
            continue
        urls.append(linkedin_url)

    return urls, skipped_no_linkedin


async def _linkedin_connection_id(db: AsyncSession, user: User) -> str | None:
    """Return the user's active LinkedIn outreach connection id, or None."""
    acct_row = await db.execute(
        select(SocialAccount).where(
            SocialAccount.user_id == user.id,
            SocialAccount.platform == Platform.linkedin,
            SocialAccount.is_active.is_(True),
        )
    )
    account = acct_row.scalars().first()
    return account.outreach_connection_id if account else None


def _beam_note_to_phantommm(note: str) -> str:
    """Translate Beam's ``{{placeholder}}`` tokens into phantommm's ``#token#``.

    phantommm scrapes each LinkedIn profile and templates ``#firstName#`` /
    ``#lastName#`` / ``#fullName#`` itself, so we map Beam's supported name
    placeholders onto those.

    LIMITATION: phantommm only knows the scraped LinkedIn profile — it has NO
    company/job data — so ``{{company_name}}`` (and any other unsupported
    ``{{token}}``) is replaced with a neutral fallback ("your team") rather than
    a real value. A recipient therefore never sees a raw mustache placeholder,
    but company-level personalization is not available on the LinkedIn channel.
    See TODO in the module report: real company personalization would require
    per-URL note rendering (Beam-side) instead of phantommm's shared template.
    """
    import re

    out = (
        note.replace("{{first_name}}", "#firstName#")
        .replace("{first_name}", "#firstName#")
        .replace("{{last_name}}", "#lastName#")
        .replace("{last_name}", "#lastName#")
        .replace("{{full_name}}", "#fullName#")
        .replace("{full_name}", "#fullName#")
        # Unsupported on this channel — neutral fallback, never a raw token.
        .replace("{{company_name}}", "your team")
        .replace("{company_name}", "your team")
    )
    # Strip any remaining {{token}} so no raw mustache reaches a recipient.
    return re.sub(r"\{\{?\s*[\w.]+\s*\}?\}", "", out).strip()


@router.post(
    "/{site_id}/{campaign_id}/linkedin-outreach",
    response_model=LinkedInOutreachResponse,
)
async def start_linkedin_outreach(
    site_id: str,
    campaign_id: str,
    body: LinkedInOutreachRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> LinkedInOutreachResponse:
    """Send LinkedIn connection requests to a campaign's segment audience.

    Real sends run through the phantommm sidecar (Beam never talks to LinkedIn
    directly). dry_run defaults ON — a real send requires ``dry_run=false``. The
    audience is resolved the same way the email send path does, then filtered to
    visitors with a LinkedIn URL that are not suppressed / do_not_contact.
    """
    await verify_site_access(db, site_id, user)
    campaign = await _get_campaign_or_404(db, site_id, campaign_id)

    touchpoint = _first_linkedin_touchpoint(campaign.plan or {})
    if touchpoint is None:
        raise HTTPException(
            status_code=400, detail="Campaign has no LinkedIn touchpoint"
        )
    if campaign.segment_id is None:
        raise HTTPException(status_code=400, detail="Campaign has no segment audience")

    # The caller must have registered a LinkedIn session with phantommm.
    connection_id = await _linkedin_connection_id(db, user)
    if not connection_id:
        raise HTTPException(
            status_code=400, detail="Connect your LinkedIn session first"
        )

    try:
        client = PhantommmClient()
    except PhantommmNotConfigured:
        raise HTTPException(status_code=503, detail="LinkedIn outreach not configured")

    # Resolve the segment audience exactly like send_campaign_emails does.
    urls, skipped_no_linkedin = await _resolve_linkedin_targets(
        db, site_id, campaign, body.limit
    )

    if not urls:
        raise HTTPException(
            status_code=400,
            detail="No audience members have a LinkedIn profile to reach",
        )

    note = _beam_note_to_phantommm(touchpoint.get("connection_note") or "")

    try:
        result = await client.start_outreach(
            connection_id=connection_id,
            urls=urls,
            note=note,
            action=body.action,
            dry_run=body.dry_run,
            limit=min(body.limit, MAX_LINKEDIN_OUTREACH_LIMIT),
        )
    except PhantommmError:
        raise HTTPException(
            status_code=502, detail="LinkedIn outreach failed to start — try again"
        )

    job_id = str(result.get("jobId") or "")
    logger.info(
        "linkedin_outreach_started",
        campaign_id=str(campaign.id),
        job_id=job_id,
        dry_run=body.dry_run,
        total_targets=len(urls),
        skipped_no_linkedin=skipped_no_linkedin,
    )
    return LinkedInOutreachResponse(
        job_id=job_id,
        dry_run=bool(result.get("dryRun", body.dry_run)),
        total_targets=len(urls),
        audience_skipped_no_linkedin=skipped_no_linkedin,
    )


@router.get(
    "/{site_id}/{campaign_id}/linkedin-outreach/{job_id}",
    response_model=LinkedInOutreachJobResponse,
)
async def get_linkedin_outreach_job(
    site_id: str,
    campaign_id: str,
    job_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> LinkedInOutreachJobResponse:
    """Proxy a phantommm outreach job's status for the campaign owner."""
    await verify_site_access(db, site_id, user)
    await _get_campaign_or_404(db, site_id, campaign_id)

    try:
        client = PhantommmClient()
    except PhantommmNotConfigured:
        raise HTTPException(status_code=503, detail="LinkedIn outreach not configured")

    try:
        job = await client.get_outreach_job(job_id)
    except PhantommmError:
        raise HTTPException(status_code=502, detail="Could not fetch outreach status")

    results = job.get("results")
    return LinkedInOutreachJobResponse(
        status=str(job.get("status") or "unknown"),
        done=int(job.get("done") or 0),
        total=int(job.get("total") or 0),
        sent=int(job.get("sent") or 0),
        results=results if isinstance(results, list) else [],
    )


@router.post(
    "/{site_id}/{campaign_id}/linkedin-outreach/schedule",
    response_model=LinkedInScheduleResponse,
)
async def schedule_linkedin_outreach(
    site_id: str,
    campaign_id: str,
    body: LinkedInScheduleRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> LinkedInScheduleResponse:
    """Schedule a durable LinkedIn drip campaign that STARTS after the step's
    suggested delay.

    Complements the immediate "Send LinkedIn outreach" endpoint: rather than a
    one-shot job, this enqueues a persistent phantommm campaign that begins only
    once the touchpoint's ``delay_hours_from_start`` has elapsed, then paces
    sends within daily limits. dry_run defaults ON — a real schedule requires
    ``dry_run=false``. Audience selection is identical to the immediate path
    (shared ``_resolve_linkedin_targets`` helper).
    """
    await verify_site_access(db, site_id, user)
    campaign = await _get_campaign_or_404(db, site_id, campaign_id)

    touchpoint = _first_linkedin_touchpoint(campaign.plan or {})
    if touchpoint is None:
        raise HTTPException(
            status_code=400, detail="Campaign has no LinkedIn touchpoint"
        )
    if campaign.segment_id is None:
        raise HTTPException(status_code=400, detail="Campaign has no segment audience")

    connection_id = await _linkedin_connection_id(db, user)
    if not connection_id:
        raise HTTPException(
            status_code=400, detail="Connect your LinkedIn session first"
        )

    # The campaign-suggested start offset for this step (hours), clamped ≥ 0.
    delay_hours = max(0, int(touchpoint.get("delay_hours_from_start") or 0))

    try:
        client = PhantommmClient()
    except PhantommmNotConfigured:
        raise HTTPException(status_code=503, detail="LinkedIn outreach not configured")

    urls, skipped_no_linkedin = await _resolve_linkedin_targets(
        db, site_id, campaign, body.limit
    )
    if not urls:
        raise HTTPException(
            status_code=400,
            detail="No audience members have a LinkedIn profile to reach",
        )

    note = _beam_note_to_phantommm(touchpoint.get("connection_note") or "")

    try:
        result = await client.start_campaign(
            connection_id=connection_id,
            urls=urls,
            note=note,
            action=body.action,
            dry_run=body.dry_run,
            delay_hours=delay_hours,
        )
    except PhantommmError:
        raise HTTPException(
            status_code=502,
            detail="LinkedIn outreach failed to schedule — try again",
        )

    # Live sends return campaignId; dry-run may omit it → empty string.
    phantommm_campaign_id = str(result.get("campaignId") or "")
    scheduled_at = result.get("scheduledAt")
    logger.info(
        "linkedin_outreach_scheduled",
        campaign_id=str(campaign.id),
        phantommm_campaign_id=phantommm_campaign_id,
        dry_run=body.dry_run,
        delay_hours=delay_hours,
        total_targets=len(urls),
        skipped_no_linkedin=skipped_no_linkedin,
    )
    return LinkedInScheduleResponse(
        campaign_id=phantommm_campaign_id,
        scheduled_at=str(scheduled_at) if scheduled_at is not None else None,
        delay_hours=delay_hours,
        dry_run=bool(result.get("dryRun", body.dry_run)),
        total_targets=len(urls),
        audience_skipped_no_linkedin=skipped_no_linkedin,
    )


@router.get(
    "/{site_id}/{campaign_id}/linkedin-outreach/campaign/{phantommm_campaign_id}",
    response_model=LinkedInCampaignDetailResponse,
)
async def get_linkedin_campaign_detail(
    site_id: str,
    campaign_id: str,
    phantommm_campaign_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> LinkedInCampaignDetailResponse:
    """Proxy a durable phantommm campaign's status for the campaign owner."""
    await verify_site_access(db, site_id, user)
    await _get_campaign_or_404(db, site_id, campaign_id)

    connection_id = await _linkedin_connection_id(db, user)
    if not connection_id:
        raise HTTPException(
            status_code=400, detail="Connect your LinkedIn session first"
        )

    try:
        client = PhantommmClient()
    except PhantommmNotConfigured:
        raise HTTPException(status_code=503, detail="LinkedIn outreach not configured")

    try:
        detail = await client.get_campaign_detail(
            phantommm_campaign_id, connection_id
        )
    except PhantommmError:
        raise HTTPException(status_code=502, detail="Could not fetch campaign status")

    counts = detail.get("counts")
    campaign_obj = detail.get("campaign")
    scheduled_at = (
        campaign_obj.get("scheduledAt") if isinstance(campaign_obj, dict) else None
    )
    days = detail.get("days")
    return LinkedInCampaignDetailResponse(
        status_counts={
            k: int(v)
            for k, v in (counts.items() if isinstance(counts, dict) else [])
            if isinstance(v, (int, float))
        },
        scheduled_at=str(scheduled_at) if scheduled_at is not None else None,
        days=days if isinstance(days, list) else [],
    )
