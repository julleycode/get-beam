"""Helpers + background jobs for the visitors router.

Extracted verbatim from routers/visitors.py to slim the router. Behavior is
unchanged. The route module re-imports these names, so existing imports
(`from apps.api.routers.visitors import _compute_visitor_stat_counts`, used by
ai.py and tests) keep resolving.
"""

from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.models.database import async_session
from apps.api.models.enrichment import EnrichmentProfile
from apps.api.models.known_contact import KnownContact
from apps.api.models.site import Site
from apps.api.models.visitor import (
    RESOLUTION_MIN_INTENT,
    IdentifiedVisitor,
    Visitor,
)
from apps.api.services.agent_visitor_filters import human_only_visitor_filter
from apps.api.services.billing import check_usage_allowed
from apps.api.services.known_hash import email_hash
from apps.api.services.osint_scanner import run_osint_scan
from apps.api.services.resolution_eligibility import (
    first_win_boost_site_ids,
    is_resolution_candidate,
    resolution_candidate_filter,
    site_resolves_all_us,
)
from apps.api.services.resolution_runner import run_resolution_for_site
from apps.api.services.social_resolver import resolve_social
from apps.api.services.usage_limits import check_resolution_attempt_budget

logger = structlog.get_logger()


# Cap on per-visitor events in an export payload. A single visitor almost never
# has this many; the cap just bounds a pathological payload. Truncation is
# surfaced in the response so it's never a silent omission.
_EXPORT_EVENT_CAP = 5000


def _row_to_dict(obj) -> dict:
    """Serialize an ORM row to a plain dict of its columns (DSAR export)."""
    return {c.key: getattr(obj, c.key) for c in obj.__table__.columns}


async def _known_visitor_ids(db: AsyncSession, site_id: str) -> set[str]:
    """Visitor ids whose identified email matches the site's known-contacts list.

    Matching is hash-vs-hash — the owner's list is stored only as HMAC hashes
    (see models/known_contact.py). We hash the identified emails in Python here
    because the HMAC key lives in the app, not the DB. Loads this site's
    identified emails + known hashes; fine at current scale. If identified rows
    grow large, add an email_hash column to identified_visitors and switch this
    to a SQL join.
    """
    known_hashes = set(
        (
            await db.execute(
                select(KnownContact.email_hash).where(KnownContact.site_id == site_id)
            )
        ).scalars().all()
    )
    if not known_hashes:
        return set()
    id_rows = await db.execute(
        select(IdentifiedVisitor.visitor_id, IdentifiedVisitor.email).where(
            IdentifiedVisitor.site_id == site_id,
            IdentifiedVisitor.email.isnot(None),
        )
    )
    return {vid for vid, em in id_rows if em and email_hash(em) in known_hashes}


async def _build_visitor_filters(
    db: AsyncSession,
    site_id: str,
    *,
    identity_status: str | None = None,
    enrichment_status: str | None = None,
    country: str | None = None,
    visitor_type: str | None = None,
    known: bool | None = None,
    ai_source: str | None = None,
    first_seen_from: datetime | None = None,
    first_seen_to: datetime | None = None,
    last_seen_from: datetime | None = None,
    last_seen_to: datetime | None = None,
    min_intent: float | None = None,
) -> list:
    """Translate the Visitors-filter query params into SQLAlchemy predicates.

    Shared by the list endpoint and the country-facet endpoint so the dropdown
    counts always reflect the same predicates as the rows. The country facet
    passes country=None on purpose (faceted search: a facet must not constrain
    its own counts, or picking a country would collapse the dropdown to that one
    country). Date bounds: *_to is EXCLUSIVE — the frontend sends the start of
    the day AFTER the chosen end date so the whole end day is included.
    """
    # AC2 (GUARD #2): every human-facing visitor query excludes synthetic
    # agent-derived rows. Applied here at the shared choke point so BOTH the list
    # endpoint and the country-facet endpoint inherit it (they both call this
    # helper), covering plan sites D1 and D6.
    filters: list = [human_only_visitor_filter()]
    if identity_status:
        filters.append(Visitor.identity_status == identity_status)
    if enrichment_status:
        filters.append(Visitor.enrichment_status == enrichment_status)
    if country:
        filters.append(Visitor.country_code == country)
    # AI-referral Source facet. A concrete label filters to that engine; the
    # "__any__" sentinel means "any AI-referred visitor" (ai_source IS NOT NULL).
    # Attribution-only — this filter never affects emailability.
    if ai_source == "__any__":
        filters.append(Visitor.ai_source.isnot(None))
    elif ai_source:
        filters.append(Visitor.ai_source == ai_source)
    # "new" = seen in a single session; "returning" = came back (2+ sessions).
    # total_sessions is the lifetime session count (gap > 30 min) and is always
    # >= 1, so "new" is effectively == 1. This is Beam's own visit signal, NOT a
    # known-customer/CRM signal (that's a later phase).
    if visitor_type == "new":
        filters.append(Visitor.total_sessions <= 1)
    elif visitor_type == "returning":
        filters.append(Visitor.total_sessions > 1)
    if known is not None:
        # "known" = email matches the owner's uploaded contacts. Resolve the
        # matching visitor ids once (hash-based) and filter on them. Empty set →
        # in_() matches nobody / notin_() matches everybody, both correct.
        known_ids = list(await _known_visitor_ids(db, site_id))
        if known:
            filters.append(Visitor.visitor_id.in_(known_ids))
        else:
            filters.append(Visitor.visitor_id.notin_(known_ids))
    if first_seen_from is not None:
        filters.append(Visitor.first_seen >= first_seen_from)
    if first_seen_to is not None:
        filters.append(Visitor.first_seen < first_seen_to)
    if last_seen_from is not None:
        filters.append(Visitor.last_seen >= last_seen_from)
    if last_seen_to is not None:
        filters.append(Visitor.last_seen < last_seen_to)
    if min_intent is not None:
        filters.append(Visitor.intent_score >= min_intent)
    return filters


async def _compute_visitor_stat_counts(db: AsyncSession, site_id: str) -> dict[str, int]:
    """Count-based site stats in 2 queries instead of 6.

    The five visitor-table counts are collapsed into a single table scan using
    conditional aggregates (``COUNT(*) FILTER (WHERE ...)``). The enrichment-
    profile count stays its own query because it targets a different table.
    Results are identical to issuing each ``COUNT`` separately — the per-site
    ``WHERE`` is applied once and every filtered aggregate is scoped under it.
    """
    site_url = (
        await db.execute(select(Site.url).where(Site.site_id == site_id))
    ).scalar_one_or_none()
    all_us_ids = [site_id] if site_resolves_all_us(site_url) else []
    # First-win boost: while the site has fewer than settings.first_win_boost_count
    # identified visitors ever, the intent floor is waived for it entirely.
    boost_ids = await first_win_boost_site_ids(db, [site_id])

    row = (
        await db.execute(
            select(
                func.count().label("total"),
                func.count()
                .filter(Visitor.identity_status == "identified")
                .label("identified"),
                func.count()
                .filter(Visitor.enrichment_status == "enriched")
                .label("enriched"),
                func.count()
                .filter(
                    and_(
                        Visitor.enrichment_status == "enriched",
                        Visitor.segmented == False,  # noqa: E712
                    )
                )
                .label("enriched_unsegmented"),
                func.count()
                .filter(
                    and_(
                        Visitor.identity_status == "anonymous",
                        resolution_candidate_filter(
                            all_us_ids,
                            no_floor_site_ids=boost_ids,
                        ),
                        Visitor.do_not_resolve.is_(False),
                    )
                )
                .label("eligible_for_resolution"),
            )
            .select_from(Visitor)
            # AC2 (GUARD #2): exclude synthetic agent-derived rows from every
            # conditional-aggregate count (all 5 inherit this per-site WHERE).
            .where(Visitor.site_id == site_id, human_only_visitor_filter())
        )
    ).one()

    # Could be enriched further (low completeness) — separate table.
    could_enrich_more = (
        await db.execute(
            select(func.count())
            .select_from(EnrichmentProfile)
            .where(
                EnrichmentProfile.site_id == site_id,
                EnrichmentProfile.enrichment_completeness < 0.6,
            )
        )
    ).scalar() or 0

    return {
        "total": row.total or 0,
        "identified": row.identified or 0,
        "enriched": row.enriched or 0,
        "could_enrich_more": could_enrich_more,
        "enriched_unsegmented": row.enriched_unsegmented or 0,
        "eligible_for_resolution": row.eligible_for_resolution or 0,
    }


async def _resolution_skip_reason(
    db: AsyncSession, site: Site, visitor: Visitor, last_attempt: datetime | None
) -> str:
    """Best-effort explanation for why an anonymous visitor hasn't resolved.

    Mirrors the gates in IdentityResolver.resolve() / run_resolution_for_site,
    checked in the order the pipeline applies them. "awaiting_next_run" means
    fully eligible — just waiting on the next sweep or a manual resolve.
    """
    # Privacy opt-out (GPC/DNT or a cascaded suppression match) is the FIRST
    # gate resolve() applies — it blocks identification by policy, not by any
    # usage limit, so it must be reported as such, never as "budget used up".
    if getattr(visitor, "do_not_resolve", False):
        return "privacy_opt_out"
    boost_ids = await first_win_boost_site_ids(db, [site.site_id])
    if not await is_resolution_candidate(
        db,
        visitor,
        site_url=site.url,
        no_floor_site_ids=boost_ids,
    ):
        return "below_intent_threshold"
    if not visitor.ip_address:
        return "no_ip_address"
    if last_attempt is not None:
        cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=30)
        if last_attempt >= cutoff:
            return "recently_attempted"
    if not await check_resolution_attempt_budget(db, site.site_id):
        return "daily_budget_exhausted"
    if not await check_usage_allowed(db, site.user_id):
        return "monthly_plan_limit_reached"
    return "awaiting_next_run"


# Human-facing copy for each skip reason. Keeps the per-row Identify endpoint
# from collapsing every "still anonymous" outcome into a misleading "daily
# budget used up" line (a max-plan site with no caps was seeing exactly that
# for privacy-opted-out visitors).
_SKIP_REASON_MESSAGES: dict[str, str] = {
    "privacy_opt_out": "This visitor opted out of identification (privacy signal / suppression list). Policy block — not a usage limit.",
    "below_intent_threshold": (
        f"Intent score is below {RESOLUTION_MIN_INTENT:g} — not eligible for identification yet."
    ),
    "no_ip_address": "No IP address captured for this visitor — can't run identity lookup.",
    "recently_attempted": "Already attempted in the last 30 days. Will retry automatically after the cooldown.",
    "daily_budget_exhausted": "Daily identification budget used up for this site. Resets tomorrow (UTC). Add your own API keys in Settings to lift the daily cap.",
    "monthly_plan_limit_reached": "You've hit your plan's monthly identification limit. Upgrade to Pro (50/mo) or Max (unlimited) — or add your own API keys to unlock.",
    "awaiting_next_run": "Eligible — couldn't identify from available providers this time.",
}

# Machine-readable limit classification for the frontend upsell router. Only
# "monthly_plan" hits are an upgrade moment (plan tiers differ ONLY on the
# monthly cap); daily caps are identical across tiers, so those stay BYOK-led
# and must NOT trigger the upgrade modal. Skip reasons absent here aren't limits.
_SKIP_REASON_LIMIT_KIND: dict[str, str] = {
    "daily_budget_exhausted": "daily_budget",
    "monthly_plan_limit_reached": "monthly_plan",
}


def _coverage_note(visitor: Visitor) -> str | None:
    """Honest reason an `unresolvable` visitor was a *structural* miss, not a
    fluke. The person-level providers (RB2B, Leadpipe) are US-only graphs, and
    IP→company only resolves corporate IPs — so a non-US visitor on a
    residential network (no company_domain) can NEVER match. Say that plainly
    instead of a bare "unresolvable", which reads as a bug to the site owner.
    Returns None when the miss isn't region-structural (e.g. US traffic, or a
    corporate IP that simply had no contact data)."""
    cc = (visitor.country_code or "").upper()
    if cc and cc != "US" and not visitor.company_domain:
        return (
            "Identity providers currently cover US traffic only. This visitor is "
            "outside the US on a residential network, so they can't be matched — "
            "this is a coverage limit of the data providers, not an error or a usage cap."
        )
    return None


async def _run_resolution_job(site_id: str, max_resolve: int = 20) -> None:
    """Background trigger for the trigger-agnostic resolution runner.

    Runs AFTER the HTTP response is sent, in its own DB session (the
    request-scoped session is already closed by the time this runs).
    All resolution logic lives in services/resolution_runner.py — shared
    with the APScheduler sweep and any future Celery/cron worker.
    """
    async with async_session() as db:
        site_result = await db.execute(select(Site).where(Site.site_id == site_id))
        site = site_result.scalar_one_or_none()
        if site is None:
            return
        await run_resolution_for_site(db, site, max_resolve=max_resolve)


async def _run_osint_scan_job(site_id: str, visitor_id: str) -> None:
    """Background OSINT account scan for one visitor.

    Runs AFTER the HTTP response, in its own DB session. Read-modify-writes
    EnrichmentProfile.social_context under the `osint_scan` key, PRESERVING any
    existing `deep_research` (social_context is otherwise overwritten wholesale
    elsewhere). Does NOT touch social_context_updated_at — that column drives the
    deep-research daily meter and an OSINT scan must not count against it.
    """
    async with async_session() as db:
        id_row = await db.execute(
            select(IdentifiedVisitor).where(
                IdentifiedVisitor.site_id == site_id,
                IdentifiedVisitor.visitor_id == visitor_id,
            )
        )
        identified = id_row.scalar_one_or_none()
        email = identified.email if identified else None

        prof_row = await db.execute(
            select(EnrichmentProfile).where(
                EnrichmentProfile.site_id == site_id,
                EnrichmentProfile.visitor_id == visitor_id,
            )
        )
        profile = prof_row.scalar_one_or_none()
        if profile is None:
            profile = EnrichmentProfile(
                visitor_id=visitor_id, site_id=site_id, enrichment_completeness=0.0
            )
            db.add(profile)
            await db.flush()

        if not email:
            blob = {
                "status": "not_identified", "accounts": [], "engines": [],
                "summary": {}, "message": "Visitor has no email to scan.",
            }
        else:
            try:
                blob = await run_osint_scan(email)
            except Exception as e:  # defensive — run_osint_scan shouldn't raise
                logger.warning("osint_scan_job_error", visitor_id=visitor_id[:8], error=str(e))
                blob = {
                    "status": "error", "accounts": [], "engines": [],
                    "summary": {}, "message": "OSINT scan failed unexpectedly.",
                }

        # Read-modify-write: reassign a NEW dict so SQLAlchemy detects the JSONB
        # change, and keep every other social_context key (e.g. deep_research).
        merged = dict(profile.social_context or {})
        merged["osint_scan"] = blob
        profile.social_context = merged
        await db.commit()
        logger.info(
            "osint_scan_job_done", visitor_id=visitor_id[:8],
            status=blob.get("status"), accounts=len(blob.get("accounts", [])),
        )


async def _run_social_resolution_job(site_id: str, visitor_id: str) -> None:
    """Background full social-resolution pipeline (stages A–F) for one visitor.

    Owns its own session. resolve_social() persists social_context itself
    (osint_scan + social_resolution + deep_research, read-modify-write).
    """
    async with async_session() as db:
        visitor = (await db.execute(
            select(Visitor).where(Visitor.site_id == site_id, Visitor.visitor_id == visitor_id)
        )).scalar_one_or_none()
        if visitor is None:
            return
        identified = (await db.execute(
            select(IdentifiedVisitor).where(
                IdentifiedVisitor.site_id == site_id,
                IdentifiedVisitor.visitor_id == visitor_id,
            )
        )).scalar_one_or_none()
        profile = (await db.execute(
            select(EnrichmentProfile).where(
                EnrichmentProfile.site_id == site_id,
                EnrichmentProfile.visitor_id == visitor_id,
            )
        )).scalar_one_or_none()
        if profile is None:
            profile = EnrichmentProfile(
                visitor_id=visitor_id, site_id=site_id, enrichment_completeness=0.0
            )
            db.add(profile)
            await db.flush()
        try:
            await resolve_social(db, visitor=visitor, identified=identified, profile=profile)
        except Exception as e:
            logger.warning("social_resolution_job_error", visitor_id=visitor_id[:8], error=str(e))
            merged = dict(profile.social_context or {})
            merged["social_resolution"] = {
                "status": "error", "profiles": [], "stages_run": [],
                "message": "Social resolution failed unexpectedly.",
            }
            profile.social_context = merged
            await db.commit()
