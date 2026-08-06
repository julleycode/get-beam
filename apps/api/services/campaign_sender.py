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

import re
from datetime import datetime, timezone
from html import escape
from urllib.parse import quote

import structlog
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.config import settings
from apps.api.models.campaign import Campaign, CampaignTouchpoint
from apps.api.models.enrichment import EnrichmentProfile
from apps.api.models.segment import SegmentMember
from apps.api.models.visitor import IdentifiedVisitor, Visitor
from apps.api.services.email_providers import gmail as gmail_client
from apps.api.services.email_providers.gmail_sender import (
    resolve_sender_for_site,
    send_via_gmail,
)
from apps.api.services.email_rate_limiter import (
    check_and_reserve_email,
    release_email_reservation,
)
from apps.api.services.email_sender import EmailSender
from apps.api.services.identity_classification import (
    is_emailable_identity,
    is_graph_candidate_provider,
    is_verified_identity,
)
from apps.api.services.link_decorator import generate_unsubscribe_token
from apps.api.services.suppression import is_email_suppressed


def _unsubscribe_footer(to_email: str) -> tuple[str, str]:
    """(unsubscribe_url, html_footer) — parity with EmailSender's own footer, for
    the Gmail path which bypasses EmailSender.send."""
    token = generate_unsubscribe_token(to_email)
    url = f"{settings.api_base_url}/unsubscribe?t={quote(token, safe='')}"
    footer = (
        f'\n<br/><br/>\n<p style="font-size:12px;color:#999;">'
        f'<a href="{escape(url, quote=True)}">Unsubscribe</a> from future emails.</p>'
    )
    return url, footer

logger = structlog.get_logger()


def _first_email_touchpoint(plan: dict) -> dict | None:
    """Return the first email touchpoint with a usable subject+body, or None."""
    for tp in plan.get("touchpoints", []):
        if tp.get("channel") == "email" and tp.get("subject") and tp.get("body"):
            return tp
    return None


# Matches any leftover {{token}} the substitutions below did not resolve, so a
# recipient never sees a raw mustache placeholder.
_LEFTOVER_TOKEN = re.compile(r"\{\{\s*[\w.]+\s*\}\}")
# Lowercase-led [bracket hints] the LLM sometimes emits ("[their industry]"),
# distinct from the capitalized [Your Name] signature stub we fill above.
_LEFTOVER_HINT = re.compile(r"\[[a-z][^\]]*\]")
# A parenthetical left hollow once a placeholder inside it is removed, e.g.
# "(especially in {{industry}})" -> "(especially in )". Only matches when every
# inner word is followed by a space before ")", i.e. the trailing token was
# stripped — legit parens like "(see below)" are preserved.
_HOLLOW_PARENS = re.compile(r"\(\s*(?:[A-Za-z]+\s+)*\)")


def _tidy(text: str) -> str:
    """Strip unresolved placeholders and the whitespace/paren debris they leave,
    so a recipient never sees a raw token or a dangling "(especially in )"."""
    text = _LEFTOVER_TOKEN.sub("", text)
    text = _LEFTOVER_HINT.sub("", text)
    text = _HOLLOW_PARENS.sub("", text)
    text = re.sub(r"\(\s+", "(", text)           # no space just inside "("
    text = re.sub(r"\s+\)", ")", text)           # no space just inside ")"
    text = re.sub(r"[ \t]{2,}", " ", text)       # collapse runs of spaces
    text = re.sub(r" +([.,!?;:])", r"\1", text)  # no space before punctuation
    return text


def _personalize(
    text: str,
    full_name: str | None,
    company_name: str | None = None,
    sender_name: str | None = None,
) -> str:
    """Fill campaign template placeholders.

    Handles ``{{first_name}}``, ``{{company_name}}`` (both single- and
    double-brace forms) and the AI planner's ``[Your Name]`` signature stub.
    Anything we can't resolve falls back to a neutral phrase, and any remaining
    ``{{token}}`` is stripped so broken templates can't ship literal mustache.
    """
    first = (full_name or "").strip().split(" ")[0] if full_name else ""
    first = first or "there"
    company = (company_name or "").strip() or "your company"
    sender = (sender_name or "").strip() or "The Beam Team"

    out = (
        text.replace("{{first_name}}", first)
        .replace("{first_name}", first)
        .replace("{{company_name}}", company)
        .replace("{company_name}", company)
        .replace("[Your Name]", sender)
    )
    return _tidy(out)


class PersonalizationGateError(RuntimeError):
    """A candidate-tier (unconfirmed) identity reached the personalized branch.

    Identity-honesty Phase 2: an unconfirmed graph guess must never be addressed
    by a guessed name/title/company. This is raised — never silently substituted —
    so a future refactor that bypasses the send-time gate fails loudly in CI
    instead of quietly regressing to guessing.
    """


def _assert_personalization_allowed(
    identity_status: str | None,
    visitor_id: str | None = None,
    resolution_provider: str | None = None,
) -> None:
    """Fail-loud guard: only a CONFIRMED identity may be personalized.

    Called at the top of the personalized branch, so the branch itself cannot be
    entered with a candidate/anonymous/unresolvable tier. Logs at ERROR with no
    PII (truncated visitor_id + provider only, matching this module's structlog
    convention) and raises.
    """
    if is_verified_identity(identity_status):
        return
    logger.error(
        "campaign_personalization_gate_violation",
        visitor_id=(visitor_id or "")[:8] or None,
        resolution_provider=resolution_provider,
        identity_status=identity_status,
    )
    raise PersonalizationGateError(
        "Refusing to personalize copy for a non-verified identity "
        f"(identity_status={identity_status!r}) — candidate-tier recipients get "
        "generic copy only."
    )


def _compose_generic(
    text: str,
    sender_name: str | None = None,
) -> str:
    """Generic composition for an unconfirmed (candidate-tier) recipient.

    Same template engine as ``_personalize`` — deliberately called with
    ``full_name=None`` and ``company_name=None`` so no guessed identity value can
    reach the copy. Placeholders resolve to the neutral fallbacks ("there",
    "your company"); the sender's own signature is still filled (that is Beam's
    own first-party data, not a guess about the recipient).
    """
    return _personalize(text, None, None, sender_name)


def _compose_for_recipient(
    identity_status: str | None,
    subject_tpl: str,
    body_tpl: str,
    full_name: str | None,
    company_name: str | None,
    sender_name: str | None = None,
    visitor_id: str | None = None,
    resolution_provider: str | None = None,
) -> tuple[str, str]:
    """Send-time personalization gate — returns ``(subject, body_html)``.

    Verified ("identified") recipients go through ``_personalize`` byte-for-byte
    unchanged. Everything else (candidate / anonymous / unknown) gets generic
    copy with zero guessed name/company merge fields.
    """
    if is_verified_identity(identity_status):
        _assert_personalization_allowed(identity_status, visitor_id, resolution_provider)
        subject = _personalize(subject_tpl, full_name, company_name, sender_name)
        body = _personalize(body_tpl, full_name, company_name, sender_name)
    else:
        subject = _compose_generic(subject_tpl, sender_name)
        body = _compose_generic(body_tpl, sender_name)
    return subject, body.replace("\n", "<br/>")


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
    from apps.api.models.user import User
    from apps.api.services.link_decorator import decorate_links

    site_row = (
        await db.execute(
            select(Site.url, Site.name, User.full_name, User.email)
            .outerjoin(User, User.id == Site.user_id)
            .where(Site.site_id == campaign.site_id)
        )
    ).first()
    site_url = site_row[0] if site_row else None
    # From-name = the site's own name (falls back to "Beam"); [Your Name]
    # signature stub → the site owner's name; Reply-To → the owner's inbox so
    # replies reach the customer, not Beam's shared address.
    site_name = (site_row[1] if site_row else None) or "Beam"
    sender_name = (site_row[2] if site_row else None) or None
    owner_email = (site_row[3] if site_row else None) or None
    site_host = urlsplit(site_url or "").netloc or None

    # If the site owner connected their Gmail, send FROM their address (no "via
    # sendgrid.info"). None → send via Beam/SendGrid as before. Resolved once;
    # cleared to None if a send hits a dead grant so the rest of the run falls
    # back to Beam instead of hammering a revoked token.
    gmail_sender = await resolve_sender_for_site(db, campaign.site_id)

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
        # identity_status lives on Visitor (not IdentifiedVisitor), joined on
        # (site_id, visitor_id) — the same predicate used in identity_resolver /
        # routers.visitors / daily_digest. Read FRESH per recipient inside the
        # send loop: that is what makes a mid-campaign candidate confirmation take
        # effect on the very next send without re-planning the campaign. A missing
        # Visitor row yields None, which is not verified → generic copy (fails
        # safe, never drops the recipient).
        #
        # Fetched LAZILY, at most once per recipient, by the closure below. The
        # confirm-gate (a few lines down) needs it BEFORE the skip-gates, but the
        # personalization gate needs it AFTER them — reading it eagerly at the top
        # would add a query for every recipient that gets skipped. This keeps the
        # query count byte-identical to before the confirm-gate was introduced.
        _identity_status_cache: list = []

        async def _identity_status() -> str | None:
            if not _identity_status_cache:
                _identity_status_cache.append(
                    (
                        await db.execute(
                            select(Visitor.identity_status).where(
                                Visitor.site_id == campaign.site_id,
                                Visitor.visitor_id == vid,
                            )
                        )
                    ).scalar_one_or_none()
                )
            return _identity_status_cache[0]

        # Never email a company-level guess (hunter/apollo map IP -> company and
        # return a RANDOM employee, not the visitor) or an unclassified provider.
        emailable = is_emailable_identity(
            iv.resolution_provider,
            getattr(iv, "source_agent_visit_id", None),
            getattr(iv, "is_abuse_flagged", False),
        )
        # D5/D10 confirm-gate. Additive-RESTRICTIVE only: it can narrow the
        # audience, never widen it beyond what is_emailable_identity() already
        # allowed. With candidate_outreach_enabled OFF (default), an UNCONFIRMED
        # graph-candidate is held back; a human-CONFIRMED one still sends, by
        # design. is_emailable_identity() itself is deliberately not parameterized.
        if (
            emailable
            and is_graph_candidate_provider(iv.resolution_provider)
            and not settings.candidate_outreach_enabled
        ):
            emailable = is_verified_identity(await _identity_status())
        if not emailable:
            summary["skipped_company_level"] += 1
            continue
        # Suppression list catches addresses opted out AFTER identification (the
        # do_not_email flag only covers rows that existed at opt-out time, and
        # this path passes no db to EmailSender so _is_suppressed is bypassed).
        if await is_email_suppressed(db, iv.email, "do_not_email"):
            summary["skipped_suppressed"] += 1
            continue

        # Idempotency fast-path: skip visitors already emailed for this campaign.
        # This is an optimization, NOT the guard — under READ COMMITTED a
        # concurrent sender's uncommitted row is invisible here, so the real
        # "never double-send" enforcement is the unique-constraint claim below.
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
        # a later run) once the cap is hit. Reserved BEFORE the claim; the slot is
        # released on every path that reserves but does not actually send.
        if not await check_and_reserve_email(campaign.site_id):
            summary["throttled"] += 1
            continue

        company_name = (
            await db.execute(
                select(EnrichmentProfile.company_name).where(
                    EnrichmentProfile.site_id == campaign.site_id,
                    EnrichmentProfile.visitor_id == vid,
                )
            )
        ).scalar_one_or_none()

        # Resolves the lazy read above (or reuses the value the confirm-gate
        # already fetched) — exactly one query per recipient that gets this far.
        identity_status = await _identity_status()

        # Identity-honesty gate: only a CONFIRMED ("identified") recipient is
        # addressed by name/company. Candidate-tier graph guesses get generic copy.
        subject, body_html = _compose_for_recipient(
            identity_status,
            subject_tpl,
            body_tpl,
            iv.full_name,
            company_name,
            sender_name,
            visitor_id=vid,
            resolution_provider=iv.resolution_provider,
        )

        # Claim the recipient by inserting the touchpoint BEFORE sending. This
        # doubles as (a) the id carrier for tracking — the open pixel (/o/{id})
        # stamps opened_at and _tp on decorated links stamps clicked_at — and
        # (b) the concurrency guard: the unique (campaign, visitor, channel)
        # constraint means a second concurrent sender's flush raises
        # IntegrityError instead of producing a duplicate email. Flush (not
        # commit) assigns the UUID and takes the index lock; a losing racer's
        # flush blocks here until we commit (→ their IntegrityError) or roll back
        # (→ they proceed).
        tp_row = CampaignTouchpoint(
            campaign_id=campaign.id,
            visitor_id=vid,
            channel="email",
            touchpoint_order=order,
            status="pending",
            content={"subject": subject},
        )
        db.add(tp_row)
        try:
            await db.flush()
        except IntegrityError:
            # Another sender already claimed this recipient — do NOT send. Undo
            # the flush and return the reserved cap slot.
            await db.rollback()
            await db.refresh(campaign)
            await release_email_reservation(campaign.site_id)
            summary["skipped_already_sent"] += 1
            continue

        # Deterministic click→identity: stamp the recipient's _bid on links to
        # their own site so the click resolves them for free (own-data, no provider).
        body_html = decorate_links(body_html, iv.email, site_host, touchpoint_id=str(tp_row.id))
        # Open-tracking pixel (overcounts under Apple MPP; clicks are the honest signal).
        body_html += (
            f'<img src="{settings.api_base_url}/o/{tp_row.id}"'
            ' width="1" height="1" alt="" style="display:none;max-height:1px;">'
        )
        sent_ok = False
        # Preferred channel: the owner's connected Gmail. On a dead grant or
        # transient Gmail error, disable Gmail for the rest of this run and fall
        # through to Beam/SendGrid so the campaign still goes out.
        if gmail_sender is not None:
            try:
                unsub_url, unsub_footer = _unsubscribe_footer(iv.email)
                await send_via_gmail(
                    db,
                    gmail_sender,
                    to_email=iv.email,
                    subject=subject,
                    body_html=body_html + unsub_footer,
                    unsubscribe_url=unsub_url,
                )
                sent_ok = True
            except (gmail_client.GmailOAuthError, RuntimeError) as exc:
                logger.warning(
                    "campaign_gmail_send_failed_fallback_beam",
                    visitor_id=vid[:8],
                    error=str(exc),
                )
                gmail_sender = None

        if not sent_ok:
            try:
                await sender.send(
                    to_email=iv.email,
                    subject=subject,
                    body_html=body_html,
                    from_name=site_name,
                    reply_to=owner_email,
                    # Echoed back on SendGrid open/click events so the webhook can
                    # attribute engagement to this (site, visitor) — owned-data-layer.
                    custom_args={"site_id": campaign.site_id, "visitor_id": vid},
                )
            except Exception as exc:
                logger.warning("campaign_email_failed", visitor_id=vid[:8], error=str(exc))
                # Discard the pending touchpoint — per-iteration commits mean the
                # rollback can only drop this row. rollback() expires ALL attached
                # objects (even with expire_on_commit=False), so refresh campaign or
                # the next loop iteration's campaign.site_id access would raise
                # MissingGreenlet (sync IO on an expired async object).
                await db.rollback()
                await db.refresh(campaign)
                # The send never went out — hand the reserved cap slot back so a
                # failed recipient doesn't permanently burn an hourly slot.
                await release_email_reservation(campaign.site_id)
                summary["failed"] += 1
                continue

        tp_row.status = "sent"
        # Naive UTC — CampaignTouchpoint.sent_at is a naive column.
        tp_row.sent_at = datetime.now(timezone.utc).replace(tzinfo=None)
        await db.commit()
        summary["sent"] += 1

    return summary
