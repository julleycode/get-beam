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

from apps.api.config import settings
from apps.api.models.campaign import Campaign, CampaignTouchpoint
from apps.api.models.segment import SegmentMember
from apps.api.models.visitor import IdentifiedVisitor
from apps.api.services.email_rate_limiter import check_and_reserve_email
from apps.api.services.email_sender import EmailSender
from apps.api.services.identity_classification import is_emailable_identity
from apps.api.services.suppression import is_email_suppressed

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
        "skipped_company_level": 0,
        "skipped_already_sent": 0,
        "throttled": 0,
        "failed": 0,
    }
    if not visitor_ids:
        return summary

    sender = EmailSender()

    # Site host for link decoration: every campaign link pointing at the customer's
    # own (Beam-pixel'd) site is stamped with the recipient's encrypted email
    # (_bid), so a click resolves that visitor deterministically on arrival. Only
    # the site's own host is decorated (the token never leaks to third parties).
    from urllib.parse import urlsplit
    from apps.api.models.site import Site
    from apps.api.services.link_decorator import decorate_links

    site_url = (
        await db.execute(select(Site.url).where(Site.site_id == campaign.site_id))
    ).scalar_one_or_none()
    site_host = urlsplit(site_url or "").netloc or None

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
        # Never email a company-level guess (hunter/apollo map IP -> company and
        # return a RANDOM employee, not the visitor) or an unclassified provider.
        if not is_emailable_identity(iv.resolution_provider):
            summary["skipped_company_level"] += 1
            continue
        # Suppression list catches addresses opted out AFTER identification (the
        # do_not_email flag only covers rows that existed at opt-out time, and
        # this path passes no db to EmailSender so _is_suppressed is bypassed).
        if await is_email_suppressed(db, iv.email, "do_not_email"):
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

        # Create the touchpoint BEFORE sending so its id can ride in the email:
        # the open pixel (/o/{id}) stamps opened_at, and _tp on decorated links
        # lets the site pixel stamp clicked_at. Flush assigns the UUID client-side.
        tp_row = CampaignTouchpoint(
            campaign_id=campaign.id,
            visitor_id=vid,
            channel="email",
            touchpoint_order=order,
            status="pending",
            content={"subject": subject},
        )
        db.add(tp_row)
        await db.flush()

        # Deterministic click→identity: stamp the recipient's _bid on links to
        # their own site so the click resolves them for free (own-data, no provider).
        body_html = decorate_links(body_html, iv.email, site_host, touchpoint_id=str(tp_row.id))
        # Open-tracking pixel (overcounts under Apple MPP; clicks are the honest signal).
        body_html += (
            f'<img src="{settings.api_base_url}/o/{tp_row.id}"'
            ' width="1" height="1" alt="" style="display:none;max-height:1px;">'
        )
        try:
            await sender.send(to_email=iv.email, subject=subject, body_html=body_html)
        except Exception as exc:
            logger.warning("campaign_email_failed", visitor_id=vid[:8], error=str(exc))
            # Discard the pending touchpoint — per-iteration commits mean the
            # rollback can only drop this row. rollback() expires ALL attached
            # objects (even with expire_on_commit=False), so refresh campaign or
            # the next loop iteration's campaign.site_id access would raise
            # MissingGreenlet (sync IO on an expired async object).
            await db.rollback()
            await db.refresh(campaign)
            summary["failed"] += 1
            continue

        tp_row.status = "sent"
        # Naive UTC — CampaignTouchpoint.sent_at is a naive column.
        tp_row.sent_at = datetime.now(timezone.utc).replace(tzinfo=None)
        await db.commit()
        summary["sent"] += 1

    return summary
