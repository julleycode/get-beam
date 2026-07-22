"""EvalLayer Phase 05 — agent visit → company/lead resolution sweep.

When an agent visit's IP belongs to a REAL company network (not a datacenter /
vendor egress), resolving it identifies a real customer whose employee happened
to run an agentic tool. This sweep feeds those — and ONLY those — into Beam's
existing human enrichment + outreach pipeline, reusing the SAME identity
resolution waterfall, budget, and 30-day no-retry logic humans get (Option B:
full waterfall reuse via a synthetic per-agent-visit Visitor row).

Data-quality caveat (by design): most datacenter/vendor agent traffic
(OpenAI/Anthropic/Perplexity crawler IPs) will NOT produce a lead — resolve()'s
own is_ip_suspicious/datacenter gate skips it, because resolving it would identify
the AI vendor as "the company", not a real customer. Only agent visits from a
real company's own (non-datacenter) network resolve.

Safety (GUARD #1): every IdentifiedVisitor row this sweep creates carries the
unforgeable ``source_agent_visit_id`` marker, written ATOMICALLY in the same
INSERT as the row (threaded through resolve() → _save_identified), so Phase 7's
``is_emailable_identity`` guard makes it non-emailable from the instant it exists
— even a person-level provider match on an agent IP can never be an outreach
target (SPEC AC10). A person-level match on an agent-originated IP is likely a
company employee, not the actual visitor — expected data-quality caveat; the
marker makes it non-emailable regardless of provider, so it is safe to allow.
"""

import structlog
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.models.agent_visit import AgentVisit
from apps.api.models.company import Company
from apps.api.models.visitor import Visitor
from apps.api.services.identity_resolver import IdentityResolver
from apps.api.services.visitor_aggregator import _upsert_company

logger = structlog.get_logger()


async def _get_or_create_synthetic_visitor(
    db: AsyncSession, agent_visit: AgentVisit
) -> Visitor:
    """Insert-or-fetch the throwaway Visitor standing in for one AgentVisit.

    Idempotent on ``uq_visitors_site_visitor`` — mirrors _save_identified's
    IntegrityError → rollback → re-fetch pattern so a concurrent sweep run can't
    crash on a duplicate insert. ``is_agent_derived=True`` and ``intent_score``
    left at the model default 0.0 (defense-in-depth: the intent>=40 eligibility
    gates in resolution_runner/resolution_tasks would never independently pick up
    a 0-intent row even if the AC2 filter were ever removed).
    """
    visitor_id = f"agent:{agent_visit.id}"
    existing = await db.execute(
        select(Visitor).where(
            Visitor.site_id == agent_visit.site_id,
            Visitor.visitor_id == visitor_id,
        )
    )
    row = existing.scalar_one_or_none()
    if row is not None:
        return row

    visitor = Visitor(
        site_id=agent_visit.site_id,
        visitor_id=visitor_id,
        ip_address=agent_visit.ip_address,
        first_seen=agent_visit.first_seen_at,
        last_seen=agent_visit.last_seen_at,
        is_agent_derived=True,
    )
    db.add(visitor)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        existing = await db.execute(
            select(Visitor).where(
                Visitor.site_id == agent_visit.site_id,
                Visitor.visitor_id == visitor_id,
            )
        )
        row = existing.scalar_one_or_none()
        if row is None:
            raise
        return row
    return visitor


async def run_company_resolution_sweep(
    db: AsyncSession, limit: int = 20
) -> dict[str, int]:
    """Resolve eligible agent visits into company/lead records. Fail-open.

    Eligibility: ``resolved_company_id IS NULL AND ip_address IS NOT NULL``. No
    ``verification_method`` gate — resolve()'s own IP-quality gates
    (is_ip_suspicious/datacenter skip) are the correct and sufficient filter; a
    verification gate would wrongly exclude legitimate ua-only agent traffic from
    real company networks.

    Each row is processed in its own try/except so one bad row can't abort the
    batch (mirrors run_resolution_for_site / run_verification_sweep). Budget and
    the 30-day no-retry rule are consumed purely via resolve()'s own
    check_daily_budget / was_recently_attempted — no separate bucket.

    Returns counters: processed (attempted), resolved (identity hit),
    companies (resolved_company_id set).
    """
    counters = {"processed": 0, "resolved": 0, "companies": 0}

    result = await db.execute(
        select(AgentVisit).where(
            AgentVisit.resolved_company_id.is_(None),
            AgentVisit.ip_address.isnot(None),
        ).limit(limit)
    )
    agent_visits = list(result.scalars().all())
    if not agent_visits:
        return counters

    resolver = IdentityResolver(db)

    for agent_visit in agent_visits:
        try:
            counters["processed"] += 1
            visitor = await _get_or_create_synthetic_visitor(db, agent_visit)

            # GUARD #1: the marker is threaded into the SAME INSERT that creates
            # the IdentifiedVisitor row (resolve() → _save_identified), so there
            # is no window where an unmarked agent-derived row is durable.
            identified = await resolver.resolve(
                visitor, source_agent_visit_id=str(agent_visit.id)
            )
            if identified is not None:
                counters["resolved"] += 1

            # resolve()'s IP→company step sets visitor.company_domain (and commits
            # it) when a domain is found. Upsert the SAME kind of Company row human
            # resolution creates, then point the agent visit at it.
            domain = getattr(visitor, "company_domain", None)
            if domain:
                await _upsert_company(db, agent_visit.site_id, domain, visitor)
                company_row = await db.execute(
                    select(Company.id).where(
                        Company.site_id == agent_visit.site_id,
                        Company.domain == domain,
                    )
                )
                company_id = company_row.scalar_one_or_none()
                if company_id is not None:
                    agent_visit.resolved_company_id = company_id
                    counters["companies"] += 1

            await db.commit()
        except Exception:
            # Per-row fail-open: one bad row must not abort the sweep. Log keys
            # only (no PII / no prompt bodies).
            await db.rollback()
            logger.exception(
                "agent_company_resolution_row_failed",
                id=str(agent_visit.id),
                site_id=agent_visit.site_id,
            )

    logger.info("agent_company_resolution_sweep_done", **counters)
    return counters
