"""Job-change detection (v1, same-tenant) — detect → corroborate → record.

Answers one question: "has an identified visitor I ALREADY know changed
employer since I last enriched them?" The baseline is this site's OWN stored
``EnrichmentProfile``, never another tenant's data.

PIPELINE ORDER (deliberate — every step below is a spend gate or a safety gate,
so they run BEFORE the paid provider call, not after):

  1. feature flag           — off by default; the service re-checks it itself
  2. Redis daily budget     — per-site cap, separate store from the DB-count
                              ``Site.daily_resolution_budget`` (SPEC AC-4)
  3. 4 safety gates         — datacenter IP / proxy-VPN / suppression /
                              do_not_resolve (SPEC AC-13), mirroring
                              identity_signals.py's write-gate block
  4. baseline lookup        — no stored profile means nothing to compare against
  5. provider call          — enricher._enrich_pdl, falling back to _enrich_apollo
  6. compare_company()      — normalization-aware diff (SPEC AC-5)
  7. corroborate()          — confidence + independent-signal gate (SPEC AC-6)
  8. record_job_change()    — one minimal before/after row (SPEC AC-7)

SAME-TENANT ONLY (SPEC AC-11). This module imports ZERO ``beam_identity_graph``
paths — no ``_upsert_beam_identity``, no ``BeamIdentityNode``. The only
cross-file reuse is ``enricher``'s provider calls and ``company_resolver``'s
``company_graph`` read, which is a STRUCTURALLY DIFFERENT table (per-IP company
attribution) from ``beam_identity_graph`` (cross-tenant person identity). The
absence of that import is the enforcement mechanism, the same way
identity_signals.py structurally cannot write an IdentifiedVisitor.

NO AUTO-SEND (SPEC AC-8). ``record_job_change`` creates a ``draft``-status
record only; this module imports no send path whatsoever.

FAILURE POSTURE: a re-check is an OPPORTUNISTIC enrichment. Every gate failure
is a silent skip that returns ``None`` — never an exception — so a re-check can
never break the ingest event path or the sweep task that called it.
"""

from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.config import settings
from apps.api.models.enrichment import EnrichmentProfile
from apps.api.models.job_change_event import JobChangeEvent
from apps.api.models.site import Site
from apps.api.models.visitor import IdentifiedVisitor, Visitor
from apps.api.services.company_resolver import (
    check_ip_privacy,
    is_datacenter_ip,
    is_proxy_or_vpn,
)
from apps.api.services.enricher import _FREE_MAIL_DOMAINS
from apps.api.services.redis_client import get_redis
from apps.api.services.suppression import is_email_suppressed

logger = structlog.get_logger()

# Source-tier confidence. UNCALIBRATED HEURISTIC (plan Known-Gap #2): these are
# placeholder numbers chosen to preserve the provider-tier ordering used
# elsewhere in this codebase, NOT values tuned against real job-change ground
# truth. Do not read them as validated thresholds.
_SOURCE_CONFIDENCE: dict[str, float] = {
    "pdl": 0.8,
    "apollo": 0.7,
    "domain_fallback": 0.2,
}

# Legal-entity suffixes stripped before comparing two company names. A small
# FIXED list on purpose — a fuzzy-match library would be a new dependency and
# would trade a false-negative problem (which is safe here) for a false-positive
# one (which AC-6 exists to prevent).
_LEGAL_SUFFIXES: tuple[str, ...] = (
    "incorporated",
    "corporation",
    "limited",
    "holdings",
    "group",
    "inc",
    "llc",
    "ltd",
    "llp",
    "plc",
    "corp",
    "gmbh",
    "bv",
    "sa",
    "ag",
    "co",
)

_PUNCTUATION = ",.()[]&/\\-_'\"`"


# ─────────────────────────── budget (SPEC AC-4) ──────────────────────────────


def _recheck_count_key(site_id: str) -> str:
    """Redis key for today's re-check counter, UTC day."""
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return f"job_change_recheck:{site_id}:{day}"


async def check_job_change_recheck_budget(site_id: str) -> bool:
    """Reserve one re-check against today's per-site cap. True = go ahead.

    Shape copied from ``usage_limits.increment_osint_usage`` — the codebase's
    existing Redis ``INCR`` + self-expiring ``EXPIRE`` idiom. Deliberately NOT
    modelled on ``Site.daily_resolution_budget``, whose check is a DB row COUNT:
    keeping the two budgets in entirely different STORES is what makes AC-4's
    isolation structural rather than merely parallel bookkeeping — there is no
    shared code path through which one counter could influence the other.

    Fails CLOSED on a Redis error. Unlike the OSINT counter (free scans, so
    fail-open is cheap), every re-check here spends a paid provider credit, so
    an unreadable counter must mean "refuse", never "allow".
    """
    try:
        redis = get_redis()
        key = _recheck_count_key(site_id)
        count = await redis.incr(key)
        if count == 1:
            await redis.expire(key, 2 * 86400)
        if count > settings.job_change_recheck_daily_cap:
            # Give the reservation back so a refused call doesn't keep inflating
            # the counter (and doesn't distort tomorrow's tuning data).
            try:
                await redis.decr(key)
            except Exception:
                pass
            return False
        return True
    except Exception as exc:
        logger.debug("job_change_budget_check_failed", site_id=site_id, error=str(exc))
        return False


# ──────────────────────── 4 safety gates (SPEC AC-13) ────────────────────────


async def _passes_recheck_gates(
    db: AsyncSession, visitor: Visitor, email: str | None
) -> bool:
    """All 4 write gates, mirroring ``identity_signals.record_signal``.

    Same guard set as first-time identification — a re-check gets no weaker
    rule (SPEC AC-13). Any failure (including an exception from a provider
    lookup) fails CLOSED and returns False; this never raises.

    Unlike identity_signals.py, which only holds an email at write time and has
    to join back through IdentifiedVisitor, this module already has the
    ``Visitor`` row in hand — so gate 4 is a direct attribute read rather than
    that module's ``_visitor_do_not_resolve`` cross-join helper.
    """
    try:
        # Gate 1: datacenter / CDN IP.
        ip = getattr(visitor, "ip_address", None)
        if ip and await is_datacenter_ip(ip):
            logger.info("job_change_skip_datacenter", visitor_id=visitor.visitor_id[:8])
            return False
        # Gate 2: proxy / VPN / Tor / hosting.
        if ip and is_proxy_or_vpn(await check_ip_privacy(ip)):
            logger.info("job_change_skip_proxy_vpn", visitor_id=visitor.visitor_id[:8])
            return False
        # Gate 3: suppression list.
        if email and await is_email_suppressed(db, email, "do_not_email"):
            logger.info("job_change_skip_suppressed", visitor_id=visitor.visitor_id[:8])
            return False
        # Gate 4: do_not_resolve sticky (GPC/DNT or explicit opt-out).
        if visitor.do_not_resolve is True:
            logger.info(
                "job_change_skip_do_not_resolve", visitor_id=visitor.visitor_id[:8]
            )
            return False
        return True
    except Exception as exc:
        logger.debug("job_change_gate_check_failed", error=str(exc))
        return False


# ──────────────────── comparison + corroboration (AC-5/AC-6) ─────────────────


def _normalize_company(name: str | None) -> str:
    """Lowercase, strip punctuation and trailing legal-entity suffixes."""
    if not name:
        return ""
    out = name.lower()
    for ch in _PUNCTUATION:
        out = out.replace(ch, " ")
    tokens = [t for t in out.split() if t]
    while tokens and tokens[-1] in _LEGAL_SUFFIXES:
        tokens.pop()
    return " ".join(tokens)


def compare_company(prior: str | None, new: str | None) -> bool:
    """True only when the two names denote a genuinely different employer.

    A missing side is never a change: no prior company means this is a
    first-time enrichment (handled by the existing resolution path), and no new
    company means the provider simply had nothing to say.
    """
    if not prior or not new:
        return False
    a, b = _normalize_company(prior), _normalize_company(new)
    if not a or not b:
        return False
    return a != b


def is_work_email_domain(domain: str | None) -> bool:
    """True for an employer-bearing domain; False for consumer mailboxes."""
    if not domain:
        return False
    d = domain.strip().lower().lstrip("@")
    return bool(d) and "." in d and d not in _FREE_MAIL_DOMAINS


def corroborate(
    source: str,
    work_email_domain: str | None,
    company_graph_hit: bool,
) -> tuple[bool, float, str | None]:
    """Gate a detected difference on confidence AND an independent signal.

    Returns ``(passes_gate, confidence, corroboration_signal_label)``.

    Two conditions, both required:
      * ``confidence >= settings.job_change_min_confidence``
      * at least one independent corroborating signal — a non-consumer email
        domain, or a ``company_graph`` IP attribution hit

    AC-6 HARD RULE: a personal-mailbox-only result (consumer domain, no
    company_graph hit) is rejected outright, regardless of numeric confidence.
    That is a structural veto, not a threshold artefact — someone switching from
    a work address to Gmail looks exactly like a job change and is exactly the
    false positive this feature must not emit.

    False negatives are the safe failure mode here; false positives generate a
    wrong outreach draft about a person's livelihood.
    """
    confidence = _SOURCE_CONFIDENCE.get(source, 0.0)

    signals: list[str] = []
    if is_work_email_domain(work_email_domain):
        signals.append("work_email_domain")
    if company_graph_hit:
        signals.append("company_graph_ip")

    if not signals:
        return (False, confidence, None)
    if confidence < settings.job_change_min_confidence:
        return (False, confidence, None)
    return (True, confidence, "+".join(signals))


# ───────────────────────────── pipeline (AC-2/AC-7) ──────────────────────────


def _email_domain(email: str | None) -> str | None:
    if not email or "@" not in email:
        return None
    return email.rsplit("@", 1)[1].strip().lower() or None


async def _identified_email(db: AsyncSession, visitor: Visitor) -> str | None:
    """The visitor's stored identified email, or None."""
    return (
        await db.execute(
            select(IdentifiedVisitor.email).where(
                IdentifiedVisitor.site_id == visitor.site_id,
                IdentifiedVisitor.visitor_id == visitor.visitor_id,
            )
        )
    ).scalars().first()


async def _company_graph_confirms(
    db: AsyncSession, ip: str | None, new_company: str | None
) -> bool:
    """True when company_graph independently attributes this IP to the new
    employer.

    ``company_graph`` is a per-IP company-attribution table — structurally NOT
    ``beam_identity_graph`` (cross-tenant person identity). Reading it here does
    not violate AC-11; conflating the two is the mistake this comment exists to
    prevent. Coverage is sparse (plan Known-Gap #3), so a miss means "no
    corroboration from this source", never "no job change".
    """
    if not ip or not new_company:
        return False
    try:
        from apps.api.services.company_resolver import _read_company_graph

        result = await _read_company_graph(db, ip)
        if result is None or result.node is None:
            return False
        return not compare_company(result.node.company_name, new_company)
    except Exception as exc:
        logger.debug("job_change_company_graph_read_failed", error=str(exc))
        return False


async def _fetch_fresh_profile(
    db: AsyncSession, visitor: Visitor, email: str
) -> tuple[dict | None, str]:
    """Re-check the person against the provider waterfall. Returns (data, source)."""
    from apps.api.services.enricher import Enricher

    enricher = Enricher(db)
    try:
        data = await enricher._enrich_pdl(email, visitor=visitor)
        if data:
            return (data, "pdl")
    except Exception as exc:
        logger.debug("job_change_pdl_failed", error=str(exc))
    try:
        data = await enricher._enrich_apollo(email, visitor=visitor)
        if data:
            return (data, "apollo")
    except Exception as exc:
        logger.debug("job_change_apollo_failed", error=str(exc))
    return (None, "domain_fallback")


async def run_recheck(
    db: AsyncSession, visitor: Visitor, site: Site
) -> JobChangeEvent | None:
    """Re-check one identified visitor for a company change. None = no event.

    Returns None (never raises) for every non-detection outcome: flag off,
    budget exhausted, a closed safety gate, no stored baseline, no provider
    match, no material company difference, or a failed corroboration gate.
    """
    try:
        # The service refuses to run with the flag off even if a caller forgot
        # to check — same belt-and-suspenders posture as agent_detection_enabled.
        if not settings.job_change_detection_enabled:
            return None

        email = await _identified_email(db, visitor)
        if not email:
            return None

        if not await _passes_recheck_gates(db, visitor, email):
            return None

        baseline = (
            await db.execute(
                select(EnrichmentProfile).where(
                    EnrichmentProfile.site_id == visitor.site_id,
                    EnrichmentProfile.visitor_id == visitor.visitor_id,
                )
            )
        ).scalar_one_or_none()
        # No stored baseline means there is nothing to compare against — that is
        # first-time enrichment, which remains resolution_tasks.py's job.
        if baseline is None or not baseline.company_name:
            return None

        # Budget is spent only once we know a paid call is actually warranted.
        if not await check_job_change_recheck_budget(visitor.site_id):
            logger.info("job_change_budget_exhausted", site_id=visitor.site_id)
            return None

        fresh, source = await _fetch_fresh_profile(db, visitor, email)
        if not fresh:
            return None

        new_company = fresh.get("company_name")
        if not compare_company(baseline.company_name, new_company):
            return None

        graph_hit = await _company_graph_confirms(
            db, getattr(visitor, "ip_address", None), new_company
        )
        passes, confidence, signal = corroborate(
            source=source,
            work_email_domain=_email_domain(email),
            company_graph_hit=graph_hit,
        )
        if not passes:
            logger.info(
                "job_change_uncorroborated",
                visitor_id=visitor.visitor_id[:8],
                confidence=confidence,
            )
            return None

        return await record_job_change(
            db,
            site=site,
            visitor=visitor,
            baseline=baseline,
            fresh=fresh,
            confidence=confidence,
            signal=signal,
        )
    except Exception as exc:
        logger.warning(
            "job_change_recheck_failed",
            visitor_id=visitor.visitor_id[:8],
            error=str(exc),
        )
        return None


async def record_job_change(
    db: AsyncSession,
    *,
    site: Site,
    visitor: Visitor,
    baseline: EnrichmentProfile,
    fresh: dict,
    confidence: float,
    signal: str | None,
) -> JobChangeEvent:
    """Persist the transition, refresh the profile, then trigger a DRAFT.

    Order matters: the ``JobChangeEvent`` row and the profile refresh commit
    FIRST, and the draft trigger runs afterwards wrapped in try/except, so a
    draft-generation failure can never lose the detection itself.

    NEVER SENDS (SPEC AC-8). The draft lands in the owner's review queue; this
    module imports no send path.
    """
    prior_company = baseline.company_name
    prior_title = baseline.job_title
    new_company = fresh.get("company_name")
    new_title = fresh.get("job_title")

    event = JobChangeEvent(
        site_id=visitor.site_id,
        visitor_id=visitor.visitor_id,
        prior_company=prior_company,
        new_company=new_company,
        prior_job_title=prior_title,
        new_job_title=new_title,
        confidence=confidence,
        corroboration_signal=signal,
    )
    db.add(event)

    # "Current" professional fields keep living on the profile and are
    # overwritten in place — existing behavior, matching _upsert_profile's
    # pattern without modifying that function.
    baseline.company_name = new_company
    if new_title:
        baseline.job_title = new_title
    baseline.enriched_at = datetime.now(timezone.utc).replace(tzinfo=None)

    await db.commit()
    await db.refresh(event)

    logger.info(
        "job_change_recorded",
        site_id=visitor.site_id,
        visitor_id=visitor.visitor_id[:8],
        confidence=confidence,
        corroboration_signal=signal,
    )

    try:
        await _trigger_job_change_draft(db, site=site, visitor=visitor, event=event)
    except Exception as exc:
        logger.warning("job_change_draft_trigger_failed", error=str(exc))

    return event


async def _trigger_job_change_draft(
    db: AsyncSession, *, site: Site, visitor: Visitor, event: JobChangeEvent
) -> None:
    """Create a DRAFT-status re-engagement draft via the existing AutoDrafter.

    Reuses ``AutoDrafter.generate_for_visitor``'s existing call shape (the same
    one ``resolution_tasks.py`` uses), passing the job change as the drafting
    context through its additive ``trigger_reason`` parameter. Nothing here
    sends: ``generate_for_visitor`` persists a ``DraftStatus.pending`` row for
    human review, and no send path is importable from this module.
    """
    from apps.api.models.user import User
    from apps.api.services.auto_drafter import AutoDrafter

    owner = (
        await db.execute(select(User).where(User.id == site.user_id))
    ).scalar_one_or_none()
    if owner is None:
        return

    full_name = (
        await db.execute(
            select(IdentifiedVisitor.full_name).where(
                IdentifiedVisitor.site_id == visitor.site_id,
                IdentifiedVisitor.visitor_id == visitor.visitor_id,
            )
        )
    ).scalars().first()

    await AutoDrafter(db).generate_for_visitor(
        visitor=visitor,
        enrichment_data={"full_name": full_name, "job_title": event.new_job_title},
        social_context={},
        user=owner,
        trigger_reason=(
            f"job_change:{event.prior_company or 'unknown'}->"
            f"{event.new_company or 'unknown'}"
        ),
    )


# ───────────────────── sweep selection (SPEC AC-3/AC-13) ─────────────────────


def stale_profile_cutoff(now: datetime | None = None) -> datetime:
    """Timestamp before which an EnrichmentProfile counts as stale."""
    now = now or datetime.now(timezone.utc)
    return now.replace(tzinfo=None) - timedelta(days=settings.job_change_staleness_days)


def select_stale_visitors_query(site_id: str | None = None, limit: int = 100):
    """Visitors whose stored profile is stale enough to warrant a re-check.

    Excludes ``do_not_resolve`` visitors AT THE QUERY LEVEL (SPEC AC-13) — the
    per-visitor gate in ``_passes_recheck_gates`` would catch them anyway, but
    filtering here means an opted-out visitor is never even selected.
    Also excludes agent-derived synthetic rows and never-identified visitors.
    """
    stmt = (
        select(Visitor, EnrichmentProfile)
        .join(
            EnrichmentProfile,
            (EnrichmentProfile.site_id == Visitor.site_id)
            & (EnrichmentProfile.visitor_id == Visitor.visitor_id),
        )
        .where(
            Visitor.identity_status != "anonymous",
            Visitor.do_not_resolve.is_(False),
            Visitor.is_agent_derived.is_(False),
            EnrichmentProfile.enriched_at < stale_profile_cutoff(),
            EnrichmentProfile.company_name.isnot(None),
        )
        .order_by(EnrichmentProfile.enriched_at.asc())
        .limit(limit)
    )
    if site_id:
        stmt = stmt.where(Visitor.site_id == site_id)
    return stmt
