"""Read-only per-account rollup (account-measurement, gap #14).

Aggregates EXISTING tables by ``visitors.company_domain`` at read time — no
schema, no job. Every query is tenant-scoped on ``site_id``:
``campaign_touchpoints`` has no site_id, so it is scoped through
``campaigns.site_id`` and joined to this site's visitor rows only.

Counts only: no person-level column (email, name, phone, ip) is selected.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

import structlog
from sqlalchemy import case, cast, distinct, exists, func, literal, or_, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.models.campaign import Campaign, CampaignTouchpoint
from apps.api.models.company import Company
from apps.api.models.outcome import CampaignClick, Conversion, ConversionGoal
from apps.api.models.visitor import Visitor
from apps.api.schemas.account_rollup import (
    AccountCampaign,
    AccountDetail,
    AccountListResponse,
    AccountRow,
)
from apps.api.services.agent_visitor_filters import human_only_visitor_filter
from apps.api.services.enricher import _FREE_MAIL_DOMAINS

logger = structlog.get_logger()

DEMO_GOAL_NAME = "Demo booked"
IDENTIFIED_STATUSES = ("identified", "merged")

# Single source for the pricing rule, used by BOTH the Python normalizer and the
# SQL predicate: optional scheme+host, then exactly /pricing or /pricing/...,
# then optional query/fragment. "/pricing-blog" does not match.
PRICING_URL_RE = r"^([a-z][a-z0-9+.-]*://[^/?#]*)?/pricing(/[^?#]*)?([?#].*)?$"
_PRICING = re.compile(PRICING_URL_RE, re.IGNORECASE)


def normalize_path(url: str) -> str:
    """Strip scheme, host, query and fragment; keep the path."""
    if not isinstance(url, str):
        return ""
    path = urlsplit(url.strip()).path if "://" in url else url.split("?", 1)[0].split("#", 1)[0]
    return path or "/"


def is_pricing_url(url: str) -> bool:
    return isinstance(url, str) and bool(_PRICING.match(url.strip()))


def _since(days: int) -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)


def _pricing_expr():
    pages = case(
        (func.jsonb_typeof(Visitor.pages_visited) == "array", Visitor.pages_visited),
        else_=cast(literal("[]"), JSONB),
    )
    pv = func.jsonb_array_elements_text(pages).table_valued("value").alias("pv")
    return exists(select(literal(1)).select_from(pv).where(pv.c.value.op("~*")(PRICING_URL_RE)))


def _members(site_id: str, since: datetime, domain: str | None = None):
    dom = func.lower(Visitor.company_domain)
    q = select(
        Visitor.visitor_id.label("visitor_id"),
        dom.label("domain"),
        func.coalesce(Visitor.canonical_visitor_id, Visitor.visitor_id).label("person"),
        Visitor.identity_status.label("identity_status"),
        Visitor.total_sessions.label("sessions"),
        Visitor.total_pageviews.label("pageviews"),
        Visitor.last_seen.label("last_seen"),
        (Visitor.last_seen >= since).label("in_window"),
        _pricing_expr().label("pricing"),
    ).where(
        Visitor.site_id == site_id,
        Visitor.company_domain.is_not(None),
        Visitor.company_domain != "",
        dom.not_in(sorted(_FREE_MAIL_DOMAINS)),
        Visitor.is_abuse_flagged.is_not(True),
        human_only_visitor_filter(),
    )
    if domain is not None:
        q = q.where(dom == domain.lower())
    return q.cte("members")


def _rollup(site_id: str, since: datetime, domain: str | None = None):
    m = _members(site_id, since, domain)
    w = m.c.in_window.is_(True)
    vagg = (
        select(
            m.c.domain,
            func.count(distinct(m.c.person)).filter(w).label("visitors"),
            func.count(distinct(m.c.person))
            .filter(w, m.c.identity_status.in_(IDENTIFIED_STATUSES))
            .label("identified_people"),
            func.coalesce(func.sum(m.c.sessions).filter(w), 0).label("sessions"),
            func.coalesce(func.sum(m.c.pageviews).filter(w), 0).label("pageviews"),
            func.count(distinct(m.c.person)).filter(w, m.c.pricing.is_(True)).label("pricing_visitors"),
            func.max(m.c.last_seen).label("last_seen"),
        )
        .group_by(m.c.domain)
        .cte("vagg")
    )
    tagg = (
        select(m.c.domain, func.count(CampaignTouchpoint.id).label("touched"))
        .select_from(m)
        .join(CampaignTouchpoint, CampaignTouchpoint.visitor_id == m.c.visitor_id)
        .join(Campaign, Campaign.id == CampaignTouchpoint.campaign_id)
        .where(
            Campaign.site_id == site_id,
            CampaignTouchpoint.status == "sent",
            CampaignTouchpoint.sent_at >= since,
        )
        .group_by(m.c.domain)
        .cte("tagg")
    )
    cagg = (
        select(m.c.domain, func.count(CampaignClick.id).label("clicks"))
        .select_from(m)
        .join(CampaignClick, CampaignClick.visitor_id == m.c.visitor_id)
        .where(CampaignClick.site_id == site_id, CampaignClick.clicked_at >= since)
        .group_by(m.c.domain)
        .cte("cagg")
    )
    vagg_conv = (
        select(
            m.c.domain,
            func.count(Conversion.id).label("conversions"),
            func.count(Conversion.id).filter(ConversionGoal.name == DEMO_GOAL_NAME).label("demo_bookings"),
        )
        .select_from(m)
        .join(Conversion, Conversion.visitor_id == m.c.visitor_id)
        .outerjoin(
            ConversionGoal,
            (ConversionGoal.id == Conversion.goal_id) & (ConversionGoal.site_id == site_id),
        )
        .where(Conversion.site_id == site_id, Conversion.occurred_at >= since)
        .group_by(m.c.domain)
        .cte("convagg")
    )
    z = lambda col: func.coalesce(col, 0)  # noqa: E731
    cols = {
        "visitors": vagg.c.visitors,
        "identified_people": vagg.c.identified_people,
        "sessions": vagg.c.sessions,
        "pageviews": vagg.c.pageviews,
        "pricing_visitors": vagg.c.pricing_visitors,
        "touched": z(tagg.c.touched),
        "clicks": z(cagg.c.clicks),
        "conversions": z(vagg_conv.c.conversions),
        "demo_bookings": z(vagg_conv.c.demo_bookings),
    }
    q = (
        select(
            vagg.c.domain,
            Company.name.label("company_name"),
            Company.industry,
            Company.employee_count,
            *[c.label(k) for k, c in cols.items()],
            vagg.c.last_seen,
        )
        .select_from(vagg)
        .outerjoin(tagg, tagg.c.domain == vagg.c.domain)
        .outerjoin(cagg, cagg.c.domain == vagg.c.domain)
        .outerjoin(vagg_conv, vagg_conv.c.domain == vagg.c.domain)
        .outerjoin(
            Company,
            (Company.site_id == site_id) & (func.lower(Company.domain) == vagg.c.domain),
        )
        .where(
            or_(
                cols["visitors"] > 0,
                cols["touched"] > 0,
                cols["clicks"] > 0,
                cols["conversions"] > 0,
            )
        )
    )
    return q, cols, vagg


_SORT_KEY = {
    "visitors": "visitors",
    "identified": "identified_people",
    "sessions": "sessions",
    "pricing": "pricing_visitors",
    "touched": "touched",
    "clicks": "clicks",
    "conversions": "conversions",
}


def _row(r) -> AccountRow:
    d = dict(r._mapping)
    for k in ("visitors", "identified_people", "sessions", "pageviews", "pricing_visitors",
              "touched", "clicks", "conversions", "demo_bookings"):
        d[k] = int(d.get(k) or 0)
    return AccountRow(**d)


async def list_accounts(
    db: AsyncSession, site_id: str, days: int, sort: str, page: int, page_size: int
) -> AccountListResponse:
    q, cols, vagg = _rollup(site_id, _since(days))
    if sort == "last_seen":
        order = vagg.c.last_seen.desc().nulls_last()
    else:
        order = cols[_SORT_KEY[sort]].desc()
    sub = q.add_columns(func.count().over().label("_total")).order_by(order, vagg.c.domain)
    rows = (
        await db.execute(sub.limit(page_size).offset((page - 1) * page_size))
    ).all()
    total = int(rows[0]._mapping["_total"]) if rows else 0
    if not rows and page > 1:
        total = int(
            (await db.execute(select(func.count()).select_from(q.subquery()))).scalar_one()
        )
    accounts = []
    for r in rows:
        d = {k: v for k, v in r._mapping.items() if k != "_total"}
        for k in cols:
            d[k] = int(d.get(k) or 0)
        accounts.append(AccountRow(**d))
    logger.info("account_rollup_listed", site_id=site_id, total=total, returned=len(accounts))
    return AccountListResponse(
        accounts=accounts, total=total, page=page, page_size=page_size, days=days, sort=sort
    )


async def get_account(
    db: AsyncSession, site_id: str, domain: str, days: int
) -> AccountDetail | None:
    domain = domain.strip().lower()
    since = _since(days)
    q, _, _ = _rollup(site_id, since, domain)
    row = (await db.execute(q)).first()
    if row is None:
        return None
    base = _row(row)

    m = _members(site_id, since, domain)
    per: dict[str, AccountCampaign] = {}
    touched = (
        await db.execute(
            select(Campaign.id, Campaign.name, func.count(CampaignTouchpoint.id))
            .select_from(m)
            .join(CampaignTouchpoint, CampaignTouchpoint.visitor_id == m.c.visitor_id)
            .join(Campaign, Campaign.id == CampaignTouchpoint.campaign_id)
            .where(
                Campaign.site_id == site_id,
                CampaignTouchpoint.status == "sent",
                CampaignTouchpoint.sent_at >= since,
            )
            .group_by(Campaign.id, Campaign.name)
        )
    ).all()
    for cid, name, n in touched:
        per[str(cid)] = AccountCampaign(campaign_id=str(cid), name=name, touched=int(n))

    async def _by_campaign(model, ts_col) -> list:
        return (
            await db.execute(
                select(Campaign.id, Campaign.name, func.count(model.id))
                .select_from(m)
                .join(model, model.visitor_id == m.c.visitor_id)
                .join(Campaign, Campaign.id == model.campaign_id)
                .where(model.site_id == site_id, Campaign.site_id == site_id, ts_col >= since)
                .group_by(Campaign.id, Campaign.name)
            )
        ).all()

    for cid, name, n in await _by_campaign(CampaignClick, CampaignClick.clicked_at):
        per.setdefault(str(cid), AccountCampaign(campaign_id=str(cid), name=name)).clicks = int(n)
    for cid, name, n in await _by_campaign(Conversion, Conversion.occurred_at):
        per.setdefault(str(cid), AccountCampaign(campaign_id=str(cid), name=name)).conversions = int(n)

    logger.info("account_rollup_detail", site_id=site_id, campaigns=len(per))
    return AccountDetail(
        **base.model_dump(),
        days=days,
        campaigns=sorted(per.values(), key=lambda c: (-c.touched, c.name)),
    )


__all__ = ["list_accounts", "get_account", "is_pricing_url", "normalize_path", "PRICING_URL_RE"]
