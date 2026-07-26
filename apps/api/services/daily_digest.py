"""Daily activity digest — the site owner's morning working report.

One email per pixel-active site per day: what happened in the last 24h, the
day's to-do list (the same items the dashboard's "Today's actions" card shows),
and the FULL detail of every visitor identified or enriched in the window —
contact address, company, role, socials, intent, pages.

Deliberately NOT the weekly ``outcome_digest``:

* ``outcome_digest`` is a WEEKLY proof-of-outcome email built to be forwarded,
  so it withholds contact details on purpose.
* THIS digest is a DAILY owner-only report and DOES carry visitor PII. It goes
  to the account owner's address only, carries no branded/forward footer, and
  says so in the body.

Trigger-agnostic: the APScheduler cron calls ``send_daily_digests()``, but it
manages its own session and takes a Postgres advisory lock, so it can move to a
Railway cron (or run alongside replicas) unchanged.
"""

from datetime import datetime, timedelta, timezone
from html import escape
from typing import NamedTuple, Sequence

import structlog
from sqlalchemy import func, or_, select, text, update

from apps.api.config import settings
from apps.api.models.campaign import Campaign
from apps.api.models.database import async_session
from apps.api.models.draft import Draft, DraftStatus
from apps.api.models.enrichment import EnrichmentProfile
from apps.api.models.site import Site
from apps.api.models.user import User
from apps.api.models.visitor import IdentifiedVisitor, Visitor
from apps.api.services.agent_visitor_filters import human_only_visitor_filter
from apps.api.services.email_sender import EmailSender
from apps.api.services.pii_crypto import decrypt_pii

logger = structlog.get_logger()

_LOCK_KEY = "beam_daily_digest"
# Stats window per digest.
_WINDOW = timedelta(hours=24)
# Don't email the same site twice in a day. 20h (not 24h) so a cron that drifts
# a few hours early never skips a day outright.
_THROTTLE = timedelta(hours=20)


class DailyStats(NamedTuple):
    new_visitors: int
    identified: int
    enriched: int
    pageviews: int


class ActionItem(NamedTuple):
    """One row of the day's to-do list. Mirrors the dashboard card's items."""

    text: str
    cta: str
    path: str


class VisitorDetail(NamedTuple):
    """A fully-detailed identified visitor. Owner-eyes-only — this carries the
    contact address and socials, which the weekly forwardable digest omits."""

    full_name: str | None
    email: str | None
    phone: str | None
    location: str | None
    job_title: str | None
    company_name: str | None
    industry: str | None
    seniority: str | None
    linkedin_url: str | None
    twitter_handle: str | None
    intent_score: float
    pages_visited: int
    is_new_today: bool


def _fmt_location(city: str | None, region: str | None, country: str | None) -> str | None:
    return ", ".join(p for p in (city, region, country) if p) or None


def _display_name(v: VisitorDetail) -> tuple[str, bool]:
    """Best available headline for a visitor, and whether it consumed the company.

    Most identity-graph hits arrive email-only (no ``full_name``), so falling
    straight to "Unnamed visitor" would label every row in a real digest that
    way. Order: real name → email local-part → company → placeholder.
    """
    if v.full_name:
        return v.full_name, False
    if v.email:
        return v.email.split("@", 1)[0], False
    if v.company_name:
        return v.company_name, True  # consumed — don't repeat it in the role line
    return "Unnamed visitor", False


def _detail_row(v: VisitorDetail) -> str:
    """Render one visitor as a table row: identity, contact, context."""
    display, company_consumed = _display_name(v)
    name = escape(display)
    badge = (
        '<span style="background:#e8f5e9;color:#2e7d32;font-size:11px;'
        'padding:1px 6px;border-radius:10px;margin-left:6px;">new</span>'
        if v.is_new_today
        else ""
    )
    role_parts = (v.job_title,) if company_consumed else (v.job_title, v.company_name)
    role = ", ".join(escape(p) for p in role_parts if p)
    extras = ", ".join(escape(p) for p in (v.seniority, v.industry) if p)
    contact_bits: list[str] = []
    if v.email:
        safe = escape(v.email)
        contact_bits.append(f'<a href="mailto:{escape(v.email, quote=True)}">{safe}</a>')
    if v.phone:
        contact_bits.append(escape(v.phone))
    if v.linkedin_url:
        contact_bits.append(
            f'<a href="{escape(v.linkedin_url, quote=True)}">LinkedIn</a>'
        )
    if v.twitter_handle:
        handle = v.twitter_handle.lstrip("@")
        contact_bits.append(
            f'<a href="https://x.com/{escape(handle, quote=True)}">@{escape(handle)}</a>'
        )
    contact = " &middot; ".join(contact_bits) or "—"
    context_bits = [f"intent {v.intent_score:.0f}", f"{v.pages_visited} pages"]
    if v.location:
        context_bits.append(escape(v.location))
    context = " &middot; ".join(context_bits)
    role_line = (
        f'<br><span style="color:#666;font-size:13px;">{role}</span>' if role else ""
    )
    extras_line = (
        f'<br><span style="color:#999;font-size:12px;">{extras}</span>' if extras else ""
    )
    return (
        '<tr style="border-top:1px solid #eee;">'
        '<td style="padding:8px 10px 8px 0;vertical-align:top;">'
        f"<strong>{name}</strong>{badge}{role_line}{extras_line}"
        "</td>"
        f'<td style="padding:8px 10px 8px 0;vertical-align:top;font-size:13px;">{contact}</td>'
        '<td style="padding:8px 0;vertical-align:top;font-size:12px;color:#666;">'
        f"{context}</td>"
        "</tr>"
    )


def build_daily_email(
    site_name: str,
    stats: DailyStats,
    actions: Sequence[ActionItem] = (),
    visitors: Sequence[VisitorDetail] = (),
    total_visitor_rows: int = 0,
) -> tuple[str, str]:
    """Build (subject, html). Pure — unit-testable without a DB."""
    subject = (
        f"Beam today: {stats.identified} identified, {stats.new_visitors} new "
        f"visitor{'s' if stats.new_visitors != 1 else ''} on {site_name}"
    )
    base = settings.frontend_url
    visitors_url = f"{base}/dashboard/visitors"

    actions_section = (
        (
            "<p><strong>Your actions today:</strong></p><ul>"
            + "".join(
                f"<li>{escape(a.text)} &mdash; "
                f'<a href="{escape(base + a.path, quote=True)}">{escape(a.cta)}</a></li>'
                for a in actions
            )
            + "</ul>"
        )
        if actions
        else "<p>Nothing needs your attention today &mdash; you&rsquo;re all caught up.</p>"
    )

    if visitors:
        more = (
            f'<p><a href="{escape(visitors_url, quote=True)}">'
            f"See all {total_visitor_rows} &rarr;</a></p>"
            if total_visitor_rows > len(visitors)
            else f'<p><a href="{escape(visitors_url, quote=True)}">Open in Beam &rarr;</a></p>'
        )
        visitors_section = (
            "<p><strong>Identified &amp; enriched in the last 24h:</strong></p>"
            '<table style="width:100%;border-collapse:collapse;font-size:14px;">'
            + "".join(_detail_row(v) for v in visitors)
            + "</table>"
            + more
        )
    else:
        visitors_section = (
            "<p>No new identified visitors in the last 24h.</p>"
            if stats.new_visitors
            else ""
        )

    html = (
        f"<p>Hi,</p>"
        f"<p>Here&rsquo;s the last 24h for <strong>{escape(site_name)}</strong>:</p>"
        f"<ul>"
        f"<li><strong>{stats.new_visitors}</strong> new visitors "
        f"({stats.pageviews} pageviews)</li>"
        f"<li><strong>{stats.identified}</strong> identified</li>"
        f"<li><strong>{stats.enriched}</strong> enriched</li>"
        f"</ul>"
        f"{actions_section}"
        f"{visitors_section}"
        f'<p style="font-size:12px;color:#999;border-top:1px solid #eee;padding-top:10px;">'
        f"This report contains your visitors&rsquo; contact details. It&rsquo;s for "
        f"the account owner &mdash; please don&rsquo;t forward it.</p>"
        f"<p>&mdash; Beam</p>"
    )
    return subject, html


async def _site_day_stats(db, site_id: str, cutoff: datetime) -> DailyStats:
    """Window counts. Agent-derived/synthetic rows are excluded everywhere."""
    visitor_row = (
        await db.execute(
            select(
                func.count().filter(Visitor.first_seen >= cutoff),
                func.coalesce(
                    func.sum(Visitor.total_pageviews).filter(
                        Visitor.last_seen >= cutoff
                    ),
                    0,
                ),
            )
            .select_from(Visitor)
            .where(Visitor.site_id == site_id, human_only_visitor_filter())
        )
    ).one()
    identified = (
        await db.execute(
            select(func.count()).where(
                IdentifiedVisitor.site_id == site_id,
                IdentifiedVisitor.resolved_at >= cutoff,
                # Agent-origin rows are never a real person — same guardrail the
                # outreach path enforces via source_agent_visit_id.
                IdentifiedVisitor.source_agent_visit_id.is_(None),
            )
        )
    ).scalar() or 0
    enriched = (
        await db.execute(
            select(func.count()).where(
                EnrichmentProfile.site_id == site_id,
                EnrichmentProfile.enriched_at >= cutoff,
            )
        )
    ).scalar() or 0
    return DailyStats(
        new_visitors=int(visitor_row[0] or 0),
        identified=int(identified),
        enriched=int(enriched),
        pageviews=int(visitor_row[1] or 0),
    )


async def _site_actions(db, site_id: str, user_id) -> list[ActionItem]:
    """The day's to-do list — same sources as the dashboard "Today's actions".

    ``_compute_visitor_stat_counts`` is the single source of truth for
    ready-to-identify / ready-to-segment; imported lazily so this service never
    pulls the router package at import time.
    """
    from apps.api.routers.visitors_helpers import _compute_visitor_stat_counts

    counts = await _compute_visitor_stat_counts(db, site_id)
    pending_drafts = (
        await db.execute(
            select(func.count()).where(
                Draft.user_id == user_id, Draft.status == DraftStatus.pending
            )
        )
    ).scalar() or 0
    campaign_row = (
        await db.execute(
            select(
                func.count().filter(Campaign.status == "draft"),
                func.count().filter(Campaign.status == "active"),
            )
            .select_from(Campaign)
            .where(Campaign.site_id == site_id)
        )
    ).one()

    def plural(n: int, word: str) -> str:
        return f"{n} {word}{'' if n == 1 else 's'}"

    items: list[ActionItem] = []
    if counts["eligible_for_resolution"]:
        items.append(
            ActionItem(
                f"{plural(counts['eligible_for_resolution'], 'visitor')} ready to identify",
                "Review",
                "/dashboard/visitors",
            )
        )
    if counts["enriched_unsegmented"]:
        items.append(
            ActionItem(
                f"{plural(counts['enriched_unsegmented'], 'enriched visitor')} ready to segment",
                "Segment",
                "/dashboard/segments",
            )
        )
    if pending_drafts:
        items.append(
            ActionItem(
                f"{plural(int(pending_drafts), 'reply draft')} waiting for approval",
                "Review",
                "/dashboard/drafts",
            )
        )
    if campaign_row[0]:
        items.append(
            ActionItem(
                f"{plural(int(campaign_row[0]), 'campaign')} awaiting approval",
                "Review",
                "/dashboard/campaigns",
            )
        )
    if campaign_row[1]:
        items.append(
            ActionItem(
                f"{plural(int(campaign_row[1]), 'campaign')} ready to send",
                "Send",
                "/dashboard/campaigns",
            )
        )
    return items


async def _visitor_details(
    db, site_id: str, cutoff: datetime, limit: int
) -> tuple[list[VisitorDetail], int]:
    """Visitors identified OR freshly enriched in the window, newest first.

    Returns (rows, total_matching) so the email can show a "see all N" link.
    PII columns are read ciphertext-first with a plaintext fallback (the
    dual-write backfill is still in flight).
    """
    window = or_(
        IdentifiedVisitor.resolved_at >= cutoff, EnrichmentProfile.enriched_at >= cutoff
    )
    base = (
        select(
            IdentifiedVisitor.full_name,
            IdentifiedVisitor.full_name_ciphertext,
            IdentifiedVisitor.email,
            IdentifiedVisitor.email_ciphertext,
            IdentifiedVisitor.phone,
            IdentifiedVisitor.city,
            IdentifiedVisitor.region,
            IdentifiedVisitor.country,
            IdentifiedVisitor.resolved_at,
            EnrichmentProfile.job_title,
            EnrichmentProfile.company_name,
            EnrichmentProfile.industry,
            EnrichmentProfile.seniority_level,
            EnrichmentProfile.linkedin_url,
            EnrichmentProfile.linkedin_url_ciphertext,
            EnrichmentProfile.twitter_handle,
            EnrichmentProfile.twitter_handle_ciphertext,
            Visitor.intent_score,
            Visitor.pages_visited,
        )
        .select_from(IdentifiedVisitor)
        .outerjoin(
            EnrichmentProfile,
            (EnrichmentProfile.site_id == IdentifiedVisitor.site_id)
            & (EnrichmentProfile.visitor_id == IdentifiedVisitor.visitor_id),
        )
        .outerjoin(
            Visitor,
            (Visitor.site_id == IdentifiedVisitor.site_id)
            & (Visitor.visitor_id == IdentifiedVisitor.visitor_id),
        )
        .where(
            IdentifiedVisitor.site_id == site_id,
            IdentifiedVisitor.source_agent_visit_id.is_(None),
            window,
        )
    )
    total = (
        await db.execute(
            select(func.count()).select_from(base.subquery())
        )
    ).scalar() or 0
    rows = (
        await db.execute(base.order_by(IdentifiedVisitor.resolved_at.desc()).limit(limit))
    ).all()

    details: list[VisitorDetail] = []
    for r in rows:
        details.append(
            VisitorDetail(
                full_name=decrypt_pii(r.full_name_ciphertext) or r.full_name,
                email=decrypt_pii(r.email_ciphertext) or r.email,
                phone=r.phone,
                location=_fmt_location(r.city, r.region, r.country),
                job_title=r.job_title,
                company_name=r.company_name,
                industry=r.industry,
                seniority=r.seniority_level,
                linkedin_url=decrypt_pii(r.linkedin_url_ciphertext) or r.linkedin_url,
                twitter_handle=decrypt_pii(r.twitter_handle_ciphertext)
                or r.twitter_handle,
                intent_score=float(r.intent_score or 0),
                pages_visited=len(r.pages_visited or []),
                is_new_today=bool(r.resolved_at and r.resolved_at >= cutoff),
            )
        )
    return details, int(total)


async def _try_acquire_lock(db) -> bool | None:
    """True = acquired, False = held elsewhere, None = unsupported (SQLite)."""
    try:
        result = await db.execute(
            text("SELECT pg_try_advisory_lock(hashtext(:key))"), {"key": _LOCK_KEY}
        )
        return bool(result.scalar())
    except Exception as exc:
        logger.warning("daily_digest_lock_unavailable", error=str(exc))
        return None


async def _release_lock(db) -> None:
    try:
        await db.execute(
            text("SELECT pg_advisory_unlock(hashtext(:key))"), {"key": _LOCK_KEY}
        )
    except Exception:
        pass


async def send_daily_digests() -> int:
    """Send the daily digest to owners of pixel-active sites. Returns sends made.

    Scope is `pixel_verified AND tracking_enabled` — a site with no live pixel
    has nothing to report, and a paused site opted out of collection. Per-site
    failures are isolated; the throttle stamp is written via a core UPDATE.
    """
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    cutoff = now - _WINDOW
    throttle_cutoff = now - _THROTTLE
    sent_count = 0

    async with async_session() as db:
        got = await _try_acquire_lock(db)
        if got is False:
            logger.info("daily_digest_locked_elsewhere")
            return 0
        try:
            rows = (
                await db.execute(
                    select(Site.site_id, Site.name, Site.user_id, User.email)
                    .join(User, User.id == Site.user_id)
                    .where(
                        Site.pixel_verified.is_(True),
                        Site.tracking_enabled.is_(True),
                        or_(
                            Site.last_daily_digest_sent_at.is_(None),
                            Site.last_daily_digest_sent_at < throttle_cutoff,
                        ),
                    )
                    .order_by(Site.created_at)
                )
            ).all()

            sender = EmailSender()
            for site_id, site_name, user_id, owner_email in rows:
                if not owner_email:
                    continue
                try:
                    stats = await _site_day_stats(db, site_id, cutoff)
                    actions = await _site_actions(db, site_id, user_id)
                    visitors, total = await _visitor_details(
                        db, site_id, cutoff, settings.daily_digest_max_visitors
                    )
                    if (
                        stats.new_visitors == 0
                        and stats.identified == 0
                        and stats.enriched == 0
                        and not actions
                    ):
                        # Nothing happened and nothing to do — no email, and no
                        # stamp, so the site is re-evaluated on the next run.
                        continue
                    subject, html = build_daily_email(
                        site_name, stats, actions, visitors, total
                    )
                    # branding=False: this is an internal working report, not the
                    # forwardable weekly proof email. Pass db so owner opt-out
                    # (unsubscribe/bounce) is still honored.
                    await sender.send(
                        to_email=owner_email,
                        subject=subject,
                        body_html=html,
                        db=db,
                        branding=False,
                    )
                    await db.execute(
                        update(Site)
                        .where(Site.site_id == site_id)
                        .values(last_daily_digest_sent_at=now)
                    )
                    await db.commit()
                    sent_count += 1
                except Exception:
                    logger.exception("daily_digest_failed", site_id=site_id)
                    await db.rollback()
        finally:
            if got:
                await _release_lock(db)

    if sent_count:
        logger.info("daily_digests_sent", count=sent_count)
    return sent_count
