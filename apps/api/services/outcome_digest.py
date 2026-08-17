"""Weekly outcomes digest: email each site owner what Beam drove this week.

"Beam this week: X emails sent, Y clicks, Z conversions ($R attributed)" —
plus a "who visited this week" highlight list, the recurring proof-of-outcome
growth buyers keep (and forward — the branded footer rides every forward).
Sites with zero sends, zero conversions AND zero identified visitors in the
window are skipped (no noise), and each site is throttled via
``sites.last_outcome_digest_sent_at`` so overlapping triggers can't double-send.

Trigger-agnostic: the APScheduler job calls ``send_weekly_outcome_digests()``,
but it manages its own session and takes a Postgres advisory lock, so it can
move to a Railway cron (or run alongside replicas) unchanged.
"""

from datetime import datetime, timedelta, timezone
from html import escape
from typing import NamedTuple, Sequence

import structlog
from sqlalchemy import func, or_, select, text, update

from apps.api.config import settings
from apps.api.models.campaign import Campaign, CampaignTouchpoint
from apps.api.models.database import async_session
from apps.api.models.enrichment import EnrichmentProfile
from apps.api.models.outcome import Conversion
from apps.api.models.site import Site
from apps.api.models.user import User
from apps.api.models.visitor import IdentifiedVisitor
from apps.api.services.campaign_stats import (
    OPEN_RATE_CAVEAT,
    opened_count_expr,
    sent_count_expr,
)
from apps.api.services.email_sender import EmailSender
from apps.api.services.identity_classification import is_emailable_identity

logger = structlog.get_logger()

_LOCK_KEY = "beam_outcome_digest"
# Stats window per digest.
_WINDOW = timedelta(days=7)
# Don't email the same site more often than this (6d so a weekly cron that
# drifts a few hours early never skips a week).
_THROTTLE = timedelta(days=6)


class DigestStats(NamedTuple):
    sent: int
    clicked: int
    conversions: int
    attributed: int
    attributed_revenue_cents: int


class DigestBenchmark(NamedTuple):
    """Optional benchmark payload for the digest line (marketing-claims-gap
    Phase 3, D1).

    Rides as a keyword-only argument to :func:`build_digest_email` rather than as
    new ``DigestStats`` fields: ``DigestStats`` is a second public structure with
    its own producer, and the digest has never rendered an open rate at all.

    ``category_open_rate`` is a pooled MEAN over >=5 opted-in sites — a category
    AVERAGE. It is never a median (sums plus a tenant count cannot yield one),
    and the word "median" must never appear on this surface.

    ``site_open_rate`` is None when the site sent nothing in the window; the line
    then renders as "no data", never as 0%.
    """

    category_label: str
    site_open_rate: float | None
    category_open_rate: float | None


class VisitorHighlight(NamedTuple):
    """A digest-safe slice of an identified visitor. Deliberately excludes the
    email address: this email is BUILT to be forwarded, so anything in it leaks
    to people outside the account."""

    full_name: str | None
    job_title: str | None
    company_name: str | None


def _visitor_line(v: VisitorHighlight) -> str:
    """Render one highlight as 'Name — Title, Company' (whatever parts exist)."""
    name = escape(v.full_name or "Someone")
    detail = ", ".join(escape(p) for p in (v.job_title, v.company_name) if p)
    return f"<li><strong>{name}</strong>{f' &mdash; {detail}' if detail else ''}</li>"


def _benchmark_line(benchmark: "DigestBenchmark | None") -> str:
    """Render the optional benchmark line, or "" when there is nothing to say.

    Two honesty rules are enforced here, not at the call site:

    * Zero sends is NOT a measured zero — with ``site_open_rate is None`` the
      line says "no sends this week", never "0%".
    * Every open-rate value carries the MPP/image-blocking caveat. The digest is
      BUILT to be forwarded, so an uncaveated open rate would travel outside the
      account and be read as fact.
    """
    if benchmark is None or benchmark.category_open_rate is None:
        return ""
    category = escape(benchmark.category_label.replace("_", " "))
    average = f"{benchmark.category_open_rate * 100:.1f}%"
    yours = (
        f"{benchmark.site_open_rate * 100:.1f}%"
        if benchmark.site_open_rate is not None
        else "no sends this week"
    )
    return (
        f"<p><strong>How you compare:</strong> your open rate is {escape(yours)} "
        f"against a {escape(average)} category average for {category} sites.</p>"
        f'<p style="font-size:12px;color:#777;">{escape(OPEN_RATE_CAVEAT)}</p>'
    )


def build_digest_email(
    site_name: str,
    stats: DigestStats,
    visitors: Sequence[VisitorHighlight] = (),
    *,
    benchmark: "DigestBenchmark | None" = None,
) -> tuple[str, str]:
    """Build (subject, html). Pure — unit-testable without a DB.

    ``benchmark`` is keyword-only and defaulted, so every existing positional
    call site is unaffected. When None (flag off, site not opted in, or no row
    cleared the k-floor) the digest renders exactly as it did before.
    """
    subject = (
        f"Beam this week: {stats.conversions} conversion"
        f"{'s' if stats.conversions != 1 else ''} for {site_name}"
    )
    revenue = (
        f" (${stats.attributed_revenue_cents / 100:,.2f} attributed)"
        if stats.attributed_revenue_cents
        else ""
    )
    outcomes_url = f"{settings.frontend_url}/dashboard/outcomes"
    visitors_url = f"{settings.frontend_url}/dashboard/visitors"
    visitors_section = (
        (
            f"<p><strong>Who visited {escape(site_name)} this week:</strong></p>"
            f"<ul>{''.join(_visitor_line(v) for v in visitors)}</ul>"
            f'<p><a href="{escape(visitors_url, quote=True)}">See all identified visitors &rarr;</a></p>'
        )
        if visitors
        else ""
    )
    # Referral CTA rides the digest only while the program is live.
    referrals_url = f"{settings.frontend_url}/dashboard/referrals"
    referral_cta = (
        (
            f'<p style="font-size:13px;color:#777;">Know someone who\'d want '
            f"this report for their own site? "
            f'<a href="{escape(referrals_url, quote=True)}">Refer them &rarr;</a> '
            f"and you both get +10 identified visitors/month.</p>"
        )
        if settings.referrals_enabled
        else ""
    )
    # Optional benchmark line. Absolute values only — NO period-over-period
    # delta is computed or rendered here: near the k-floor, differencing
    # consecutive periods can narrow an individual tenant's numbers.
    benchmark_section = _benchmark_line(benchmark)
    html = (
        f"<p>Hi,</p>"
        f"<p>Your Beam week for <strong>{escape(site_name)}</strong>:</p>"
        f"<ul>"
        f"<li><strong>{stats.sent}</strong> campaign emails sent</li>"
        f"<li><strong>{stats.clicked}</strong> clicks back to your site</li>"
        f"<li><strong>{stats.conversions}</strong> conversions — "
        f"<strong>{stats.attributed}</strong> driven by Beam campaigns{escape(revenue)}</li>"
        f"</ul>"
        f"{benchmark_section}"
        f"{visitors_section}"
        f'<p><a href="{escape(outcomes_url, quote=True)}">See the full outcomes report &rarr;</a></p>'
        f"{referral_cta}"
        f"<p>&mdash; Beam</p>"
    )
    return subject, html


async def _top_visitors_this_week(
    db, site_id: str, cutoff: datetime, limit: int = 8
) -> list[VisitorHighlight]:
    """Top identified visitors of the window, digest-safe fields only.

    Ranking happens in Python (provider classification lives in
    identity_classification, not SQL): person-level identities first, then
    anything with a name or company; rows with neither are dropped — an
    anonymous bullet would just be noise in a report meant to impress.
    """
    rows = (
        await db.execute(
            select(
                IdentifiedVisitor.full_name,
                IdentifiedVisitor.resolution_provider,
                EnrichmentProfile.job_title,
                EnrichmentProfile.company_name,
            )
            .outerjoin(
                EnrichmentProfile,
                (EnrichmentProfile.site_id == IdentifiedVisitor.site_id)
                & (EnrichmentProfile.visitor_id == IdentifiedVisitor.visitor_id),
            )
            .where(
                IdentifiedVisitor.site_id == site_id,
                IdentifiedVisitor.resolved_at >= cutoff,
            )
            .order_by(IdentifiedVisitor.resolved_at.desc())
            .limit(25)
        )
    ).all()

    person_level: list[VisitorHighlight] = []
    rest: list[VisitorHighlight] = []
    for full_name, provider, job_title, company_name in rows:
        if not full_name and not company_name:
            continue
        highlight = VisitorHighlight(full_name, job_title, company_name)
        (person_level if is_emailable_identity(provider) else rest).append(highlight)
    return (person_level + rest)[:limit]


async def _site_week_stats(db, site_id: str, cutoff: datetime) -> DigestStats:
    tp_row = (
        await db.execute(
            select(
                func.count().filter(
                    CampaignTouchpoint.status == "sent",
                    CampaignTouchpoint.sent_at >= cutoff,
                ),
                func.count().filter(
                    CampaignTouchpoint.clicked_at.is_not(None),
                    CampaignTouchpoint.sent_at >= cutoff,
                ),
            )
            .select_from(CampaignTouchpoint)
            .join(Campaign, Campaign.id == CampaignTouchpoint.campaign_id)
            .where(Campaign.site_id == site_id)
        )
    ).one()
    conv_row = (
        await db.execute(
            select(
                func.count(),
                func.count().filter(Conversion.attribution == "campaign"),
                func.coalesce(
                    func.sum(Conversion.value_cents).filter(
                        Conversion.attribution == "campaign"
                    ),
                    0,
                ),
            ).where(Conversion.site_id == site_id, Conversion.occurred_at >= cutoff)
        )
    ).one()
    return DigestStats(
        sent=int(tp_row[0] or 0),
        clicked=int(tp_row[1] or 0),
        conversions=int(conv_row[0] or 0),
        attributed=int(conv_row[1] or 0),
        attributed_revenue_cents=int(conv_row[2] or 0),
    )


async def _site_benchmark(
    db, site_id: str, category: str | None, opted_in: bool, cutoff: datetime
) -> DigestBenchmark | None:
    """Build the digest benchmark payload, or None to render nothing.

    Returns None when the feature flag is off, when the site has not opted in
    (write-nothing/read-nothing-when-blocked), or when no category row cleared
    the k-floor. Never raises into the digest send loop.
    """
    if not settings.campaign_benchmark_enabled or not opted_in:
        return None
    from apps.api.services.campaign_benchmark import benchmark_for_category

    row = await benchmark_for_category(db, category)
    if row is None or not row.sends:
        return None
    site_row = (
        await db.execute(
            select(sent_count_expr(cutoff), opened_count_expr(cutoff))
            .select_from(CampaignTouchpoint)
            .join(Campaign, Campaign.id == CampaignTouchpoint.campaign_id)
            .where(Campaign.site_id == site_id)
        )
    ).one()
    sends, opens = int(site_row[0] or 0), int(site_row[1] or 0)
    return DigestBenchmark(
        category_label=row.category_normalized,
        # None (not 0.0) when nothing was sent — no sends is not a measured zero.
        site_open_rate=(opens / sends) if sends else None,
        category_open_rate=row.opens / row.sends,
    )


async def _try_acquire_lock(db) -> bool | None:
    """True = acquired, False = held elsewhere, None = unsupported (SQLite)."""
    try:
        result = await db.execute(
            text("SELECT pg_try_advisory_lock(hashtext(:key))"), {"key": _LOCK_KEY}
        )
        return bool(result.scalar())
    except Exception as exc:
        logger.warning("outcome_digest_lock_unavailable", error=str(exc))
        return None


async def _release_lock(db) -> None:
    try:
        await db.execute(
            text("SELECT pg_advisory_unlock(hashtext(:key))"), {"key": _LOCK_KEY}
        )
    except Exception:
        pass


async def send_weekly_outcome_digests() -> int:
    """Send the weekly digest to owners of active sites. Returns sends made.

    Per-site failures are isolated; the throttle stamp is written via a core
    UPDATE (no ORM expiry games after a rollback).
    """
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    cutoff = now - _WINDOW
    throttle_cutoff = now - _THROTTLE
    sent_count = 0

    async with async_session() as db:
        got = await _try_acquire_lock(db)
        if got is False:
            logger.info("outcome_digest_locked_elsewhere")
            return 0
        try:
            rows = (
                await db.execute(
                    select(
                        Site.site_id,
                        Site.name,
                        User.email,
                        Site.category,
                        Site.benchmark_contribution_enabled,
                    )
                    .join(User, User.id == Site.user_id)
                    .where(
                        or_(
                            Site.last_outcome_digest_sent_at.is_(None),
                            Site.last_outcome_digest_sent_at < throttle_cutoff,
                        )
                    )
                    .order_by(Site.created_at)
                )
            ).all()

            sender = EmailSender()
            for site_id, site_name, owner_email, category, benchmark_opt_in in rows:
                if not owner_email:
                    continue
                try:
                    stats = await _site_week_stats(db, site_id, cutoff)
                    visitors = await _top_visitors_this_week(db, site_id, cutoff)
                    if stats.sent == 0 and stats.conversions == 0 and not visitors:
                        # Nothing happened — no email, and no stamp so the site
                        # is re-evaluated on the next run. Identified visitors
                        # alone DO earn a digest: pre-campaign owners forwarding
                        # a "who visited" report is the growth loop.
                        continue
                    benchmark = await _site_benchmark(
                        db, site_id, category, bool(benchmark_opt_in), cutoff
                    )
                    subject, html = build_digest_email(
                        site_name, stats, visitors, benchmark=benchmark
                    )
                    # Pass db so recipient opt-out (unsubscribe/bounce) is honored.
                    await sender.send(
                        to_email=owner_email,
                        subject=subject,
                        body_html=html,
                        db=db,
                        branding=True,
                    )
                    await db.execute(
                        update(Site)
                        .where(Site.site_id == site_id)
                        .values(last_outcome_digest_sent_at=now)
                    )
                    await db.commit()
                    sent_count += 1
                except Exception:
                    logger.exception("outcome_digest_failed", site_id=site_id)
                    await db.rollback()
        finally:
            if got:
                await _release_lock(db)

    if sent_count:
        logger.info("outcome_digests_sent", count=sent_count)
    return sent_count
