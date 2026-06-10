"""Campaign email send executor with CAN-SPAM guardrails.

Only callable for campaigns the user has explicitly activated (the human-approval
gate is enforced by the router, which requires ``status == "active"``). For each
recipient this:
  1. resolves the email from the identified-visitor record,
  2. skips ``do_not_email`` (unsubscribed / hard-bounced) recipients,
  3. honors the per-site hourly send cap,
  4. is idempotent per (campaign, visitor) via CampaignTouchpoint rows,
  5. sends through EmailSender, which injects a signed unsubscribe link.
"""

from datetime import datetime, timezone

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.models.campaign import Campaign, CampaignTouchpoint
from apps.api.models.segment import SegmentMember
from apps.api.models.visitor import IdentifiedVisitor
from apps.api.services.email_rate_limiter import check_and_reserve_email
from apps.api.services.email_sender import EmailSender

logger = structlog.get_logger()


def _first_email_touchpoint(plan: dict) -> dict | None:
    """Return the first email touchpoint with a usable subject+body, or None."""
    for tp in plan.get("touchpoints", []):
        if tp.get("channel") == "email" and tp.get("subject") and tp.get("body"):
            return tp
    return None


def _personalize(text: str, full_name: str | None) -> str:
    first = (full_name or "").strip().split(" ")[0] if full_name else ""
    first = first or "there"
    return text.replace("{{first_name}}", first).replace("{first_name}", first)


async def send_campaign_emails(db: AsyncSession, campaign: Campaign) -> dict:
    """Send the campaign's email touchpoint to its segment audience.

    Returns a summary dict. Raises ValueError (caller maps to 400) if the campaign
    has no email touchpoint or no segment audience.
    """
    touchpoint = _first_email_touchpoint(campaign.plan or {})
    if touchpoint is None:
        raise ValueError("Campaign has no email touchpoint to send")
    if campaign.segment_id is None:
        raise ValueError("Campaign has no segment audience")

    subject_tpl = touchpoint["subject"]
    body_tpl = touchpoint["body"]
    order = int(touchpoint.get("step") or 1)

    member_rows = await db.execute(
        select(SegmentMember.visitor_id).where(SegmentMember.segment_id == campaign.segment_id)
    )
    visitor_ids = [r[0] for r in member_rows.all()]

    summary = {
        "total_audience": len(visitor_ids),
        "sent": 0,
        "skipped_no_email": 0,
        "skipped_suppressed": 0,
        "skipped_already_sent": 0,
        "throttled": 0,
        "failed": 0,
    }
    if not visitor_ids:
        return summary

    sender = EmailSender()

    for vid in visitor_ids:
        iv_row = await db.execute(
            select(IdentifiedVisitor).where(
                IdentifiedVisitor.site_id == campaign.site_id,
                IdentifiedVisitor.visitor_id == vid,
            )
        )
        iv = iv_row.scalar_one_or_none()
        if iv is None or not iv.email:
            summary["skipped_no_email"] += 1
            continue
        if iv.do_not_email:
            summary["skipped_suppressed"] += 1
            continue

        # Idempotency: never email the same visitor twice for this campaign step.
        existing = await db.execute(
            select(CampaignTouchpoint).where(
                CampaignTouchpoint.campaign_id == campaign.id,
                CampaignTouchpoint.visitor_id == vid,
                CampaignTouchpoint.channel == "email",
                CampaignTouchpoint.status == "sent",
            )
        )
        if existing.scalar_one_or_none() is not None:
            summary["skipped_already_sent"] += 1
            continue

        # Per-site hourly cap — stop sending this visitor (and leave the rest for
        # a later run) once the cap is hit.
        if not await check_and_reserve_email(campaign.site_id):
            summary["throttled"] += 1
            continue

        subject = _personalize(subject_tpl, iv.full_name)
        body_html = _personalize(body_tpl, iv.full_name).replace("\n", "<br/>")
        try:
            await sender.send(to_email=iv.email, subject=subject, body_html=body_html)
        except Exception as exc:
            logger.warning("campaign_email_failed", visitor_id=vid[:8], error=str(exc))
            summary["failed"] += 1
            continue

        db.add(
            CampaignTouchpoint(
                campaign_id=campaign.id,
                visitor_id=vid,
                channel="email",
                touchpoint_order=order,
                status="sent",
                content={"subject": subject},
                # Naive UTC — CampaignTouchpoint.sent_at is a naive column.
                sent_at=datetime.now(timezone.utc).replace(tzinfo=None),
            )
        )
        await db.commit()
        summary["sent"] += 1

    return summary
