"""Per-site KPI funnel — the numbers a growth marketer needs to judge ROI.

Walks the loop beam actually owns: visitors → identified → high-intent (the leads
worth acting on) → acted (outreach drafted for those leads). Every tier is real,
queried from existing tables — no fabricated metrics.

Reply rate + the wedge metric (visitor-reply-rate vs cold) are the holy grail but
need reply tracking that doesn't exist yet (`Message.replied` is never written), so
`reply_tracking_available` is False until that's wired — we surface the gap, not a
fake number.
"""

from datetime import datetime, timedelta

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.models.draft import Draft, DraftStatus
from apps.api.models.visitor import Visitor

logger = structlog.get_logger()

# Same intent bar as the resolution sweep + hot-alert: a "qualified" lead.
HIGH_INTENT = 40


def derive_rates(visitors: int, identified: int, high_intent: int, acted_high: int) -> dict:
    """Derived ratios from the raw funnel counts. Pure — unit-testable.

    `action_rate` is the one that matters: of your qualified (identified +
    high-intent) leads, how many did you actually reach out to?
    """
    return {
        "identify_rate": round(identified / visitors, 4) if visitors else 0.0,
        "action_rate": round(min(acted_high, high_intent) / high_intent, 4)
        if high_intent
        else 0.0,
    }


async def compute_kpis(db: AsyncSession, site_id: str, days: int = 30) -> dict:
    """The KPI funnel for one site over the trailing `days`."""
    since = datetime.utcnow() - timedelta(days=days)
    base = (
        select(func.count())
        .select_from(Visitor)
        .where(Visitor.site_id == site_id, Visitor.last_seen >= since)
    )

    async def count(stmt) -> int:
        return (await db.execute(stmt)).scalar() or 0

    visitors = await count(base)
    identified = await count(base.where(Visitor.identity_status == "identified"))
    # Identity-honesty Phase 1 (B4) — explicit decision for this site: candidates
    # are reported as their OWN funnel number, never folded into `identified` and
    # never silently dropped. `identified` keeps its existing meaning (CONFIRMED
    # identities only), so every downstream rate below stays honest.
    candidates = await count(base.where(Visitor.identity_status == "candidate"))
    enriched = await count(base.where(Visitor.enrichment_status == "enriched"))
    # Decision (B4): high_intent / acted_high stay CONFIRMED-only. These feed the
    # "qualified lead" rates; counting unconfirmed guesses there would reintroduce
    # exactly the overstatement this program exists to remove.
    high_intent = await count(
        base.where(
            Visitor.identity_status == "identified",
            Visitor.intent_score >= HIGH_INTENT,
        )
    )

    # Acted = distinct site visitors we've drafted outreach for. `acted_high` is
    # the same but restricted to the qualified (identified + high-intent) leads.
    hi_vids = select(Visitor.visitor_id).where(
        Visitor.site_id == site_id,
        Visitor.identity_status == "identified",
        Visitor.intent_score >= HIGH_INTENT,
    )
    site_vids = select(Visitor.visitor_id).where(Visitor.site_id == site_id)
    acted = await count(
        select(func.count(func.distinct(Draft.visitor_id))).where(
            Draft.visitor_id.in_(site_vids), Draft.visitor_id.isnot(None)
        )
    )
    acted_high = await count(
        select(func.count(func.distinct(Draft.visitor_id))).where(
            Draft.visitor_id.in_(hi_vids)
        )
    )
    sent = await count(
        select(func.count(func.distinct(Draft.visitor_id))).where(
            Draft.visitor_id.in_(site_vids), Draft.status == DraftStatus.sent
        )
    )

    rates = derive_rates(visitors, identified, high_intent, acted_high)
    logger.info("kpis_computed", site_id=site_id, visitors=visitors, high_intent=high_intent)

    return {
        "site_id": site_id,
        "window_days": days,
        "visitors": visitors,
        "identified": identified,
        "candidates": candidates,
        "enriched": enriched,
        "high_intent": high_intent,
        "acted": acted,
        "acted_high_intent": acted_high,
        "sent": sent,
        "identify_rate": rates["identify_rate"],
        "action_rate": rates["action_rate"],
        # Reply rate + wedge need reply tracking (not built yet) — don't fake it.
        "reply_tracking_available": False,
    }
