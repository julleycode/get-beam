"""Clay-style identity resolution with parallel provider execution.

Identity graphs (Leadpipe, Capturify, RB2B) run in parallel via
asyncio.gather — first match wins. If none match, IP→Company
providers (PDL + IPinfo) also run in parallel, then feed Hunter/Apollo
sequentially for person-level enrichment.

Providers:
  Identity Graphs (parallel): Leadpipe ~35%, Capturify ~40%, RB2B ~30%
  IP → Company (parallel):    PDL ~30-40%, IPinfo ~20-30%
  Company → Person (seq):     Hunter ~50%, Apollo ~40%

Provider HTTP/parse logic lives in apps/api/services/identity_providers/ as
mixins composed onto IdentityResolver below. Orchestration (resolve), shared
state, and persistence stay here. This module re-exports the shared HTTP
helpers (``_url_to_host``, ``_http_retry``, …) so existing imports and test
patch targets keep working after the split.
"""

import asyncio
import time
from datetime import datetime, timedelta, timezone

import httpx
import structlog
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.config import settings
from apps.api.models.beam_identity import BeamIdentityNode
from apps.api.models.site import Site
from apps.api.models.visitor import IdentifiedVisitor, ResolutionLog, Visitor
from apps.api.services.company_resolver import (
    check_ip_privacy,
    is_ip_suspicious,
    is_privacy_relay_ip,
)
from apps.api.services.identity_classification import (
    PAID_PERSON_GRAPH_PROVIDERS,
    is_graph_candidate_provider,
    is_verified_identity,
    name_email_consistent,
)
from apps.api.services.usage_logger import log_api_call

# Re-exported for backward compatibility: callers and tests import these names
# from this module (e.g. `from ...identity_resolver import _url_to_host`, and
# `@patch("...identity_resolver.settings")`).
from apps.api.services.identity_providers.base import (  # noqa: F401
    REDIS_RESOLUTION_PREFIX,
    RESOLUTION_CACHE_TTL,
    RESOLUTION_OUTCOME_MATCH,
    RESOLUTION_OUTCOME_NO_MATCH,
    RESOLUTION_OUTCOME_PROVIDER_UNAVAILABLE,
    RESOLUTION_OUTCOMES,
    _TRANSIENT_HTTP_STATUSES,
    HttpRetryMixin,
    ProviderNotConfiguredError,
    ProviderUnavailableError,
    _http_retry,
    _is_transient_http_error,
    _url_to_host,
    safe_failure_detail,
)
from apps.api.services.identity_providers.apollo import ApolloMixin
from apps.api.services.identity_providers.capturify import CapturifyMixin
from apps.api.services.identity_providers.hunter import HunterMixin
from apps.api.services.identity_providers.ipinfo import IPinfoMixin
from apps.api.services.identity_providers.leadpipe import LeadpipeMixin
from apps.api.services.identity_providers.matching import MatchingMixin
from apps.api.services.identity_providers.pdl import PDLMixin
from apps.api.services.identity_providers.rb2b import RB2BMixin

logger = structlog.get_logger()

# ── Provider-tier verdicts ────────────────────────────────────────────────
# A "tier" is a group of providers that can answer the same question, so a
# visitor is only written off once EVERY tier that could have matched them has
# actually spoken. Counted PER TIER, never merged into one pair of counters:
# leadpipe/capturify/rb2b share one account, so a single healthy ipinfo would
# otherwise mask all three being dead and the write-off would fire anyway.
TIER_ANSWERED = "answered"
TIER_ALL_UNAVAILABLE = "all_unavailable"
TIER_NOT_APPLICABLE = "not_applicable"

# Retry schedule for a visitor held back by a dead tier. ~31h total: long
# enough to cover a full day of vendor outage, short enough that a dead
# CREDENTIAL (which no amount of waiting fixes) stops burning sweep slots.
# Running past the last step marks the visitor unresolvable as before.
RESOLUTION_DEFER_BACKOFF = (
    timedelta(minutes=15),
    timedelta(hours=1),
    timedelta(hours=6),
    timedelta(hours=24),
)


def tier_verdict(attempted: int, unavailable: int) -> str:
    """Classify one provider tier from its attempt counts.

    ``attempted`` excludes providers that were disabled, keyless, or not
    configured for this site: they never looked, so they can neither prove a
    no-match nor an outage. Keeping them in the denominator would defer every
    visitor of every site that simply has not switched a provider on.
    """
    if attempted == 0:
        return TIER_NOT_APPLICABLE
    if unavailable >= attempted:
        return TIER_ALL_UNAVAILABLE
    return TIER_ANSWERED


class IdentityResolver(
    LeadpipeMixin,
    CapturifyMixin,
    RB2BMixin,
    PDLMixin,
    IPinfoMixin,
    HunterMixin,
    ApolloMixin,
    MatchingMixin,
    HttpRetryMixin,
):
    def __init__(self, db: AsyncSession, redis_client: object | None = None) -> None:
        self.db = db
        if redis_client is None:
            try:
                from apps.api.services.redis_client import get_redis
                self.redis = get_redis()
            except Exception:
                self.redis = None
        else:
            self.redis = redis_client
        # site_id -> bare hostname, for scoping provider queries to one site.
        self._site_domain_cache: dict[str, str | None] = {}
        # EvalLayer Phase 05 (GUARD #1): agent-origin marker for the in-flight
        # resolve() call. Set at the top of resolve(); read by _save_identified so
        # the marker lands in the same INSERT as the IdentifiedVisitor row.
        self._active_source_agent_visit_id: str | None = None

    async def _site_domain(self, site_id: str) -> str | None:
        """Bare hostname for a site's URL (e.g. 'grade.coach'), used to scope a
        provider query to this site instead of the whole account. Cached per
        instance — a sweep reuses one resolver across one site's visitors."""
        if site_id in self._site_domain_cache:
            return self._site_domain_cache[site_id]
        url = (
            await self.db.execute(select(Site.url).where(Site.site_id == site_id))
        ).scalar_one_or_none()
        host = _url_to_host(url)
        self._site_domain_cache[site_id] = host
        return host

    async def check_daily_budget(self, site_id: str) -> bool:
        """Daily attempt budget: distinct visitors tried today vs the
        per-site cap (Site.daily_resolution_budget, default 50).

        Previously counted ResolutionLog ROWS against the global default —
        each visitor writes one row per provider tried (2-8 rows), so the
        budget exhausted after ~3-8 visitors and the per-site setting was
        ignored entirely.
        """
        from apps.api.services.usage_limits import check_resolution_attempt_budget

        return await check_resolution_attempt_budget(self.db, site_id)

    async def was_recently_attempted(self, site_id: str, visitor_id: str) -> bool:
        cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=30)
        result = await self.db.execute(
            select(ResolutionLog).where(
                ResolutionLog.site_id == site_id,
                ResolutionLog.visitor_id == visitor_id,
                ResolutionLog.created_at >= cutoff,
            ).limit(1)
        )
        return result.scalar_one_or_none() is not None

    # ──────────────────── Helper: Domain Dedup ────────────────────

    async def _count_identified_for_domain(self, site_id: str, domain: str) -> int:
        """Count how many IdentifiedVisitors already exist for this domain+site combo.

        Used to offset Hunter/Apollo calls so each visitor from the same company
        IP range gets a different contact rather than always the first result.
        """
        result = await self.db.execute(
            select(func.count())
            .select_from(IdentifiedVisitor)
            .join(Visitor, IdentifiedVisitor.visitor_id == Visitor.visitor_id)
            .where(
                Visitor.company_domain == domain,
                IdentifiedVisitor.site_id == site_id,
            )
        )
        return result.scalar() or 0

    # ──────────────────── Helper: Suppression check ────────────────────

    async def _is_email_opted_out(self, visitor: Visitor) -> bool:
        """True if any email captured for this visitor is on the suppression
        list for do_not_process. Used to refuse resolution before spending."""
        from apps.api.models.visitor_email import VisitorEmail
        from apps.api.services.suppression import is_email_suppressed

        try:
            rows = await self.db.execute(
                select(VisitorEmail.email).where(
                    VisitorEmail.site_id == visitor.site_id,
                    VisitorEmail.visitor_id == visitor.visitor_id,
                )
            )
            for (email,) in rows.all():
                if await is_email_suppressed(self.db, email, "do_not_process"):
                    return True
        except Exception as exc:
            logger.warning("suppression_check_failed", error=str(exc))
        return False

    async def _email_suppressed(self, email: str) -> bool:
        """True if a specific email is on the do_not_process suppression list.
        Used by the owned reconciliation paths to avoid re-copying an identity
        that opted out AFTER the original was identified."""
        from apps.api.services.suppression import is_email_suppressed

        try:
            return await is_email_suppressed(self.db, email, "do_not_process")
        except Exception as exc:
            logger.warning("suppression_email_check_failed", error=str(exc))
            return False

    async def _identified_for_origin(
        self, site_id: str, origin_visitor_id: str
    ) -> IdentifiedVisitor | None:
        """Resolve an original (root) visitor_id to its IdentifiedVisitor row,
        following one canonical-merge hop.

        The durable _rta_svid points at the ROOT visitor_id. Usually that root
        owns the IdentifiedVisitor row; but if the root was itself merged by
        email-dedup (`_save_identified` sets canonical_visitor_id and writes NO
        row for the merged visitor), follow that single hop so the chain doesn't
        dead-end and fall back to a paid lookup."""
        direct = (
            await self.db.execute(
                select(IdentifiedVisitor).where(
                    IdentifiedVisitor.site_id == site_id,
                    IdentifiedVisitor.visitor_id == origin_visitor_id,
                ).limit(1)
            )
        ).scalar_one_or_none()
        if direct:
            return direct
        canon = (
            await self.db.execute(
                select(Visitor.canonical_visitor_id).where(
                    Visitor.site_id == site_id,
                    Visitor.visitor_id == origin_visitor_id,
                ).limit(1)
            )
        ).scalar_one_or_none()
        if canon and canon != origin_visitor_id:
            return (
                await self.db.execute(
                    select(IdentifiedVisitor).where(
                        IdentifiedVisitor.site_id == site_id,
                        IdentifiedVisitor.visitor_id == canon,
                    ).limit(1)
                )
            ).scalar_one_or_none()
        return None

    async def _origin_is_verified(self, prior: IdentifiedVisitor) -> bool:
        """Whether the ORIGIN visitor behind an inherited identity is confirmed.

        Identity-honesty Phase 1: the deterministic continuity paths
        (svid_reconcile, fingerprint_match) copy an existing identity forward.
        That copy must inherit the origin's TIER, not silently upgrade it — a
        candidate-tier guess must never become a flat "identified" just because
        the same person came back on a fresh client id or the same device.
        """
        status = (
            await self.db.execute(
                select(Visitor.identity_status).where(
                    Visitor.site_id == prior.site_id,
                    Visitor.visitor_id == prior.visitor_id,
                ).limit(1)
            )
        ).scalar_one_or_none()
        return is_verified_identity(status)

    # ──────────────────── Pre-waterfall: Prior Signal Check ────────────────────

    async def _check_prior_signals(
        self, visitor: Visitor, deterministic_only: bool = False
    ) -> IdentifiedVisitor | None:
        """Check for existing identification signals BEFORE the IP waterfall.

        Checks (in order):
        0. Server-cookie reconciliation — if this returning visitor's client id
           was wiped but the _rta_svid server cookie pointed back to an original
           visitor_id that was already identified, copy that identity for free.
        1. visitor_emails table — if this visitor_id has a captured email,
           use it to enrich directly via PDL (no IP credit needed).
        2. Fingerprint match — if another visitor with the same browser fingerprint
           was already identified, copy their identity to this visitor.

        Returns an IdentifiedVisitor if a signal produces a match, else None.
        """
        from apps.api.models.visitor_email import VisitorEmail

        # ── Check 0: Durable server-cookie (_rta_svid) reconciliation ──
        # DETERMINISTIC (not a fingerprint guess): the original visitor_id is
        # known exactly. If that original was already identified on this site,
        # this is the same person returning — copy the identity, no provider spend.
        svid = getattr(visitor, "server_visitor_id", None)
        if svid and svid != visitor.visitor_id:
            try:
                prior = await self._identified_for_origin(visitor.site_id, svid)
                # Identity-honesty Phase 1 (A1b): only inherit from an origin whose
                # identity is actually CONFIRMED. Without this check a candidate-tier
                # graph guess launders itself into a flat "identified" the moment the
                # visitor returns with a wiped client id but an intact _rta_svid
                # cookie. An unconfirmed origin falls through so this visitor runs
                # its own waterfall instead of inheriting a guess.
                if prior and not await self._origin_is_verified(prior):
                    logger.info(
                        "svid_reconcile_skipped_unverified_origin",
                        visitor_id=visitor.visitor_id[:8],
                    )
                    prior = None
                if prior and (prior.email or prior.full_name):
                    # do_not_process: the ORIGINAL may have opted out AFTER being
                    # identified. The new (wiped-client) visitor has no captured
                    # email of its own, so the resolve() suppression gate can't see
                    # it — re-check here before re-copying a suppressed identity.
                    if prior.email and await self._email_suppressed(prior.email):
                        logger.info(
                            "svid_reconcile_skipped_suppressed",
                            visitor_id=visitor.visitor_id[:8],
                        )
                    else:
                        logger.info(
                            "prior_signal_svid_reconcile",
                            visitor_id=visitor.visitor_id[:8],
                            canonical=svid[:8],
                        )
                        return await self._save_identified(
                            visitor,
                            {
                                "email": prior.email,
                                "full_name": prior.full_name,
                                "city": prior.city,
                                "region": prior.region,
                                "country": prior.country,
                                "confidence_score": 0.90,  # deterministic — above fingerprint (0.75)
                            },
                            "svid_reconcile",
                        )
            except Exception as exc:
                logger.warning("prior_signal_svid_check_failed", error=str(exc))

        # ── Check 1: Captured email for this visitor ──
        # Match this visitor_id OR the durable server_visitor_id (_rta_svid). An
        # email captured by an email-CLICK redirect binds to the svid before the
        # person's first pixel visit; without following svid here that click would
        # be missed when they later land on the site under a fresh client id.
        try:
            vid_candidates = [visitor.visitor_id]
            svid_c = getattr(visitor, "server_visitor_id", None)
            if svid_c and svid_c != visitor.visitor_id:
                vid_candidates.append(svid_c)
            email_result = await self.db.execute(
                select(VisitorEmail.email)
                .where(
                    VisitorEmail.site_id == visitor.site_id,
                    VisitorEmail.visitor_id.in_(vid_candidates),
                )
                .order_by(VisitorEmail.created_at.desc())
                .limit(1)
            )
            captured_email = email_result.scalar_one_or_none()

            if captured_email:
                logger.info(
                    "prior_signal_email_found",
                    visitor_id=visitor.visitor_id[:8],
                    email_domain=captured_email.split("@")[-1],
                )
                # The email is already OWNED ($0). Only spend a PDL credit to
                # enrich it inline when explicitly enabled — otherwise save it as
                # a form_capture and let the post-resolution enricher fill job data.
                if settings.enrich_captured_email_pdl:
                    enriched = await self._enrich_email_pdl(visitor, captured_email)
                    if enriched:
                        return enriched
                # Free cross-customer enrichment: if this exact email was already
                # identified WITH a name on any Beam site, inherit that name — a
                # deterministic email match (owned data, no provider spend). This
                # is what fills the name that P3 stopped paying PDL to fetch.
                node = await self._graph_node_by_email(captured_email)
                graph_name = node.full_name if node else None
                # Full-profile cross-tenant reuse (owned-data-layer): inherit the
                # graph node's geo fields, not just the name. getattr keeps this
                # safe for nodes/stubs predating the city/region/country columns.
                return await self._save_identified(
                    visitor,
                    {
                        "email": captured_email,
                        "full_name": graph_name,
                        "city": getattr(node, "city", None) if node else None,
                        "region": getattr(node, "region", None) if node else None,
                        "country": getattr(node, "country", None) if node else None,
                        # Slightly higher when corroborated by the cross-customer graph.
                        "confidence_score": 0.85 if graph_name else 0.80,
                    },
                    "form_capture",
                )
        except Exception as exc:
            logger.warning("prior_signal_email_check_failed", error=str(exc))

        # ── Check 2: Fingerprint match against already-identified visitors ──
        # Prefer the fp3 hash (base signals + installed fonts + audio render): it
        # carries more entropy than fp2, so a v3 hit is a stronger claim and gets
        # the higher confidence. Falls back to the fp2 column for visitors stored
        # before fp3 existed, older pixel builds, and the async window before fp3
        # resolves on the client.
        fp_v3 = getattr(visitor, "fingerprint_v3", None)
        fp_col = Visitor.fingerprint_v3 if fp_v3 else Visitor.fingerprint
        fp_val = fp_v3 or getattr(visitor, "fingerprint", None)
        if fp_val:
            try:
                fp_result = await self.db.execute(
                    select(IdentifiedVisitor)
                    .join(Visitor, IdentifiedVisitor.visitor_id == Visitor.visitor_id)
                    .where(
                        Visitor.site_id == visitor.site_id,
                        fp_col == fp_val,
                        Visitor.visitor_id != visitor.visitor_id,
                        # Identity-honesty Phase 1 (A1c): only inherit from a
                        # CONFIRMED origin. A fingerprint match against a
                        # candidate-tier origin must not auto-copy "identified"
                        # forward — it falls through so this visitor runs its own
                        # waterfall instead of inheriting an unverified guess.
                        Visitor.identity_status == "identified",
                    )
                    .order_by(IdentifiedVisitor.resolved_at.desc())
                    .limit(1)
                )
                matched = fp_result.scalar_one_or_none()

                if matched and matched.email and await self._email_suppressed(matched.email):
                    # Same do_not_process guard as Check 0: the matched person may
                    # have opted out after being identified; don't re-copy them.
                    logger.info(
                        "fingerprint_match_skipped_suppressed",
                        visitor_id=visitor.visitor_id[:8],
                    )
                    matched = None

                if matched:
                    logger.info(
                        "prior_signal_fingerprint_match",
                        visitor_id=visitor.visitor_id[:8],
                        matched_visitor=matched.visitor_id[:8],
                        fp_version=3 if fp_v3 else 2,
                    )
                    # Copy identity to this visitor
                    return await self._save_identified(
                        visitor,
                        {
                            "email": matched.email,
                            "full_name": matched.full_name,
                            "city": matched.city,
                            "region": matched.region,
                            "country": matched.country,
                            # fingerprint match — below the 0.90 deterministic
                            # svid path either way; fp3 carries more entropy than
                            # fp2, so a v3 hit is a slightly stronger claim.
                            "confidence_score": 0.80 if fp_v3 else 0.75,
                        },
                        "fingerprint_match",
                    )
            except Exception as exc:
                logger.warning("prior_signal_fingerprint_check_failed", error=str(exc))

        # ── Check 3: Beam Identity Network (cross-customer graph) ──
        # Identity-honesty Phase 1 (B1): the cross-tenant graph is a GUESS, not a
        # deterministic signal. When the caller only wants deterministic upgrade
        # signals (the candidate re-sweep), stop here — re-running a guess on a
        # visitor who is already a candidate can never promote them, it would only
        # churn the same unconfirmed data.
        if deterministic_only:
            return None
        result = await self._check_beam_identity_network(visitor)
        if result:
            return result

        return None

    # ──────────────────── Main Waterfall ────────────────────

    async def resolve(
        self,
        visitor: Visitor,
        source_agent_visit_id: str | None = None,
        force_retry: bool = False,
        deterministic_only: bool = False,
    ) -> IdentifiedVisitor | None:
        """Identity resolution with parallel provider execution.

        Flow:
        -1. Pre-waterfall: captured emails + fingerprint matches
        0.  Identity Graphs (parallel): Leadpipe, Capturify, RB2B
        1-2. IP→Company (parallel): PDL + IPinfo
        3.  Hunter (domain → employee emails)
        4.  Apollo (domain → contact)

        ``source_agent_visit_id`` (EvalLayer Phase 05, GUARD #1): when the
        agent-company-resolution sweep resolves a synthetic per-agent-visit
        Visitor, it passes the originating AgentVisit.id string here. The value
        is threaded — via ``self._active_source_agent_visit_id`` — to the single
        ``IdentifiedVisitor(...)`` constructor in ``_save_identified`` so the
        unforgeable agent-origin marker is written in the SAME INSERT+COMMIT that
        creates the row (no deferred UPDATE, no window). Every existing (human)
        caller omits it → ``None`` → byte-identical behavior. Using instance state
        rather than threading the kwarg through every intermediate method keeps
        the change contained to this file and, critically, also covers the
        provider mixins (hunter/apollo/pdl) whose ``_save_identified`` calls would
        otherwise need editing — closing the atomicity gap on EVERY resolution
        path, not just the ones inside this module.

        ``force_retry`` is the manual per-row retry path: a human deliberately
        re-running a visitor whose prior attempt may have happened while a
        provider was down (402/403 outage rows are indistinguishable from real
        no-matches in ``resolution_logs`` — the recorded cost is 0.0 either way).
        It bypasses ONLY the 30-day recency gate. The daily budget, billing,
        ``do_not_resolve``/suppression, and VPN gates all still apply.
        """
        # GUARD #1: set fresh at the top of every resolve() call. Sequential per
        # row in the sweep; every human caller passes None and resets it here, so
        # no value ever leaks between calls.
        self._active_source_agent_visit_id = source_agent_visit_id

        # ── Privacy guard: visitor opted out (GPC/DNT or suppression) ──
        # A visitor who signaled Global Privacy Control / Do Not Track must NEVER
        # be resolved to a real identity, regardless of caller (sweep, manual
        # Identify button, or per-row endpoint). Single choke point for that policy.
        if getattr(visitor, "do_not_resolve", False):
            logger.info("resolution_skipped_opted_out", visitor_id=visitor.visitor_id[:8])
            return None

        # ── Suppression list: a known email on the do-not-process list ──
        # Catches the window where a Do Not Process/Sell request was filed by
        # email before this visitor's do_not_resolve flag was cascaded (e.g. the
        # email was captured after the request). Cheap: one indexed lookup, and
        # most anonymous visitors have no captured email so it short-circuits.
        if await self._is_email_opted_out(visitor):
            logger.info("resolution_skipped_suppressed", visitor_id=visitor.visitor_id[:8])
            return None

        # ── Pre-waterfall: check prior signals (form capture, fingerprint) ──
        # These are free, high-confidence, and work on residential IPs, so they
        # run BEFORE the 30-day recency gate and the daily budget — a visitor who
        # failed a paid lookup but LATER submits an email via a form must still be
        # identified, not skipped for 30 days.
        result = await self._check_prior_signals(
            visitor, deterministic_only=deterministic_only
        )
        if result:
            return result

        # Identity-honesty Phase 1 (B1): candidate re-sweep. A candidate already
        # HAS a graph guess on file — re-running the paid/graph waterfall could
        # only produce another guess, which must never auto-promote them. Stop
        # after the deterministic signals above; only a first-party capture or a
        # human confirm moves a candidate forward.
        if deterministic_only:
            return None

        # ── Paid provider waterfall gates ──
        # The 30-day recency skip and daily budget only guard the PAID providers
        # below, not the free prior-signal path above.
        if not force_retry and await self.was_recently_attempted(
            visitor.site_id, visitor.visitor_id
        ):
            logger.info("resolution_skipped_recent_attempt", visitor_id=visitor.visitor_id[:8])
            return None

        if not await self.check_daily_budget(visitor.site_id):
            logger.warning("resolution_budget_exhausted", site_id=visitor.site_id)
            return None

        if not getattr(visitor, "ip_address", None):
            logger.info("resolution_skipped_no_ip", visitor_id=visitor.visitor_id[:8])
            visitor.identity_status = "unresolvable"
            await self.db.commit()
            return None

        # ── Privacy-relay / VPN / proxy — skip paid person-ID for masked IPs ──
        # Local prefix check first (fail-closed for known iCloud Private Relay
        # egress) so missing IPinfo token cannot let 2a09:bac3::/32 through.
        if is_privacy_relay_ip(visitor.ip_address):
            logger.info(
                "resolution_skipped_privacy_relay",
                visitor_id=visitor.visitor_id[:8],
                ip_prefix=str(visitor.ip_address)[:12],
            )
            visitor.identity_status = "vpn_filtered"
            await self.db.commit()
            return None
        if settings.ipinfo_token:
            try:
                privacy = await check_ip_privacy(visitor.ip_address)
                if is_ip_suspicious(privacy):
                    logger.info(
                        "resolution_skipped_vpn",
                        visitor_id=visitor.visitor_id[:8],
                        privacy=privacy,
                    )
                    visitor.identity_status = "vpn_filtered"
                    await self.db.commit()
                    return None
            except Exception as exc:
                logger.debug("vpn_check_failed", error=str(exc))

        # ══════════════════════════════════════════════════════════════
        # Step 0: Identity Graphs — PARALLEL person-level identification
        # Leadpipe, Capturify, RB2B run concurrently via asyncio.gather.
        # ══════════════════════════════════════════════════════════════

        # Verdict per tier, so the write-off at the end of this method can tell
        # "nobody matched" from "nobody was able to answer".
        tier_verdicts: dict[str, str] = {}

        result = await self._resolve_identity_graphs_parallel(
            visitor, tier_verdicts=tier_verdicts
        )
        if result:
            return result

        # ══════════════════════════════════════════════════════════════
        # Steps 1-2: IP → Company — PARALLEL fallback
        # PDL IP Enrich + IPinfo run concurrently. First domain wins.
        # ══════════════════════════════════════════════════════════════

        company_domain: str | None = None
        # A cache hit means this tier never ran, so it can neither prove nor
        # disprove an outage — "not applicable" is the honest default.
        ip_verdict = TIER_NOT_APPLICABLE

        # ── Redis cache check: IP → domain ──
        cache_key = f"{REDIS_RESOLUTION_PREFIX}{visitor.ip_address}"
        if self.redis:
            try:
                cached = await self.redis.get(cache_key)
                if cached is not None:
                    if cached == "__none__":
                        logger.info("resolution_cache_miss_hit", ip=visitor.ip_address[:8])
                        company_domain = None
                    else:
                        logger.info("resolution_cache_hit", ip=visitor.ip_address[:8])
                        company_domain = cached
            except Exception:
                pass  # Redis failure is non-fatal

        if company_domain is None and (not self.redis or not await self._redis_has_key(cache_key)):
            company_domain, ip_verdict = await self._resolve_ip_company_parallel(
                visitor
            )

            # ── Cache the result (hit or miss) ──
            if self.redis:
                try:
                    if company_domain:
                        await self.redis.setex(cache_key, RESOLUTION_CACHE_TTL, company_domain)
                    elif ip_verdict != TIER_ALL_UNAVAILABLE:
                        await self.redis.setex(cache_key, 86400, "__none__")
                    # An empty result from a dead tier says nothing about the IP.
                    # Caching it as "__none__" for 24h would keep skipping the
                    # IP→company step long after the providers came back.
                except Exception:
                    pass

        if company_domain:
            # Store company domain on visitor for future use
            visitor.company_domain = company_domain
            await self.db.commit()

            # Durable company graph write-through for the paid IP→company hit
            # (owned-data-layer). Flag-gated: byte-identical when off. Best-effort.
            if settings.company_graph_enabled and visitor.ip_address:
                from apps.api.services.company_resolver import _write_through_company_graph

                await _write_through_company_graph(
                    self.db, visitor.ip_address, company_domain, None, "paid_ip", 0.7
                )

            # ── Step 3: Hunter (domain → employee emails) ──
            result = await self._try_hunter_domain(visitor, company_domain)
            if result:
                return result

            # ── Step 4: Apollo (domain → contact lookup) ──
            result = await self._try_apollo(visitor, company_domain)
            if result:
                return result

        # No match from any provider — but "nobody matched" and "nobody could
        # answer" must not share an ending. `unresolvable` is terminal: both
        # sweeps select `anonymous` only, so writing it during an outage deletes
        # the visitor from every future run over a fault that was ours to wait
        # out. When a tier that COULD have matched was entirely down, hold the
        # row at `anonymous` behind a watermark instead and let it come back.
        #
        # The watermark is a column, not a Redis breaker: the cost that matters
        # is the sweep SLOT, and only a column can be part of the sweep's WHERE.
        # A breaker skips the HTTP call but the row is still selected, still
        # ranked top by intent, and still crowds out newer visitors.
        person_verdict = tier_verdicts.get("person_graph", TIER_NOT_APPLICABLE)
        if TIER_ALL_UNAVAILABLE in (person_verdict, ip_verdict):
            attempt = (visitor.resolution_defer_count or 0) + 1
            if attempt <= len(RESOLUTION_DEFER_BACKOFF):
                visitor.resolution_defer_count = attempt
                visitor.resolution_deferred_until = datetime.now(
                    timezone.utc
                ).replace(tzinfo=None) + RESOLUTION_DEFER_BACKOFF[attempt - 1]
                logger.info(
                    "resolution_deferred_provider_outage",
                    visitor_id=visitor.visitor_id[:8],
                    person_graph=person_verdict,
                    ip_company=ip_verdict,
                    attempt=attempt,
                    deferred_until=visitor.resolution_deferred_until.isoformat(),
                )
                await self.db.commit()
                return None
            # Past the last backoff step. An outage this long is a dead
            # credential, not a blip — waiting more only holds sweep slots.
            logger.warning(
                "resolution_defer_exhausted",
                visitor_id=visitor.visitor_id[:8],
                person_graph=person_verdict,
                ip_company=ip_verdict,
                attempts=attempt - 1,
            )

        # Terminal. Clear the watermark so a later revival (IP change) or manual
        # Retry starts from a clean backoff instead of inheriting a spent one.
        visitor.resolution_deferred_until = None
        visitor.resolution_defer_count = 0
        visitor.identity_status = "unresolvable"
        await self.db.commit()
        return None

    # ──────────────────── Parallel Orchestrators ────────────────────

    _GRAPH_TIMEOUT = 5.0  # seconds per identity graph provider

    async def _resolve_identity_graphs_parallel(
        self, visitor: Visitor, *, tier_verdicts: dict[str, str] | None = None
    ) -> IdentifiedVisitor | None:
        """Run Leadpipe, Capturify, RB2B in parallel. Save first match.

        ``tier_verdicts`` is an optional caller-owned dict this writes the
        person-graph verdict into under ``"person_graph"``. It is a keyword
        out-param rather than an extra return value so the nine existing call
        sites that assert on the returned row keep working untouched — the same
        shape as the ``outcome`` keyword on ``_log_resolution``. (The IP tier
        returns its verdict instead, because its caller needs it inline, right
        at the call site, to decide whether to write the negative cache.)
        """

        # A disabled provider passes a None key, so the existing `if not api_key`
        # guard below skips it cleanly — same path as a missing key.
        providers = [
            # leadpipe_pull_enabled gates the POLL only. Turning it off retires
            # `GET /v1/data` from the waterfall while leaving the webhook ingest
            # path (routers/webhooks.py) writing under the same provider name.
            ("leadpipe", settings.leadpipe_api_key if (settings.leadpipe_enabled and settings.leadpipe_pull_enabled) else None, self._call_leadpipe_api, 0.0),
            ("capturify", settings.capturify_api_key if settings.capturify_enabled else None, self._call_capturify_api, 0.0),
            ("rb2b", settings.rb2b_api_key if settings.rb2b_enabled else None, self._call_rb2b_api, 0.09),
        ]

        async def _fetch(
            name: str, api_key: str | None, call_fn
        ) -> tuple[str, dict | None, int, bool, str | None]:
            """Return the provider's payload plus *why* it produced no payload.

            The failure reason has to survive back to the caller: `data is None`
            alone cannot distinguish "answered, nobody matched" from "never
            answered", and only the latter must skip the ledger.
            """
            if not api_key:
                return (name, None, 0, False, None)
            start = time.monotonic()
            unavailable_detail: str | None = None
            try:
                data = await asyncio.wait_for(
                    call_fn(visitor), timeout=self._GRAPH_TIMEOUT
                )
            except ProviderNotConfiguredError as exc:
                # Never wired up for this site — not an attempt at all. Returning
                # attempted=False takes the same path as a missing API key: no
                # ledger row, no 30-day lock, no budget spend. A no-match here
                # would record "we looked and found nobody" about a provider that
                # was structurally unable to look.
                logger.debug(
                    "identity_graph_not_configured",
                    provider=name,
                    reason=exc.detail,
                    visitor_id=visitor.visitor_id[:8],
                )
                return (name, None, 0, False, None)
            except asyncio.TimeoutError:
                logger.warning(
                    "identity_graph_timeout",
                    provider=name,
                    visitor_id=visitor.visitor_id[:8],
                )
                data = None
                unavailable_detail = "timeout"
            except ProviderUnavailableError as exc:
                logger.warning(
                    "identity_graph_unavailable",
                    provider=name,
                    error=str(exc),
                    visitor_id=visitor.visitor_id[:8],
                )
                data = None
                unavailable_detail = exc.detail or "provider unavailable"
            except (httpx.TransportError, httpx.HTTPStatusError) as exc:
                # Transport/status failures survived tenacity — the provider
                # never delivered a verdict.
                logger.warning(
                    "identity_graph_error",
                    provider=name,
                    error=str(exc),
                    visitor_id=visitor.visitor_id[:8],
                )
                data = None
                unavailable_detail = safe_failure_detail(exc)
            except Exception as exc:
                # An unclassified crash is a bug in OUR parsing, not a provider
                # outage. Treat it as no_match so the 30-day lock still applies:
                # the plan's own risk table says lean toward locking when unsure,
                # because "never lock" turns a parse bug into a retry storm that
                # re-hits the provider on every sweep.
                logger.warning(
                    "identity_graph_unexpected_error",
                    provider=name,
                    error=str(exc),
                    visitor_id=visitor.visitor_id[:8],
                )
                data = None
            elapsed = int((time.monotonic() - start) * 1000)
            return (name, data, elapsed, True, unavailable_detail)

        results = await asyncio.gather(
            *[_fetch(n, k, c) for n, k, c, _ in providers],
            return_exceptions=True,
        )

        best_name: str | None = None
        best_data: dict | None = None
        best_idx: int | None = None
        best_elapsed = 0
        graph_attempted = 0
        graph_unavailable = 0

        for i, r in enumerate(results):
            if isinstance(r, BaseException):
                logger.warning(
                    "identity_graph_gather_exc",
                    provider=providers[i][0],
                    error=str(r),
                )
                continue
            name, data, elapsed, attempted, unavailable_detail = r
            if not attempted:
                continue
            # Counted before the match short-circuit below, so a tier that both
            # matched and had a dead member is still scored honestly.
            graph_attempted += 1
            if unavailable_detail:
                graph_unavailable += 1
            # Defer ledger write for the first successful payload until after
            # _save_identified — name/email reject must not leave success=True.
            if data and best_data is None:
                best_name = name
                best_data = data
                best_idx = i
                best_elapsed = elapsed
                continue
            success_cost = providers[i][3] if data else 0.0
            await self._log_resolution(
                visitor,
                name,
                data is not None,
                success_cost,
                elapsed,
                outcome=(
                    RESOLUTION_OUTCOME_PROVIDER_UNAVAILABLE
                    if unavailable_detail
                    else None
                ),
                detail=unavailable_detail,
            )

        if tier_verdicts is not None:
            tier_verdicts["person_graph"] = tier_verdict(
                graph_attempted, graph_unavailable
            )

        if best_data and best_name is not None and best_idx is not None:
            logger.info(
                "identity_graph_identified",
                provider=best_name,
                visitor_id=visitor.visitor_id[:8],
                email=(best_data.get("email", "")[:5] + "***"
                       if best_data.get("email") else None),
            )
            row = await self._save_identified(visitor, best_data, best_name)
            cost = providers[best_idx][3] if row is not None else 0.0
            await self._log_resolution(
                visitor, best_name, row is not None, cost, best_elapsed
            )
            return row

        return None

    async def _resolve_ip_company_parallel(
        self, visitor: Visitor
    ) -> tuple[str | None, str]:
        """Run PDL IP Enrich + IPinfo in parallel.

        Returns ``(first domain or None, tier verdict)``. The verdict is part of
        the return rather than an out-param because the caller needs it in the
        same breath as the domain: a bare ``None`` cannot tell "this IP belongs
        to no company" from "both providers were down", and caching the former's
        answer for the latter's reason blanks the IP for 24h even after the
        providers recover.
        """

        async def _fetch_domain(
            label: str, call_fn
        ) -> tuple[str | None, int, str | None]:
            """Resolve a company domain, keeping the reason for an empty result."""
            start = time.monotonic()
            unavailable_detail: str | None = None
            try:
                domain = await asyncio.wait_for(
                    call_fn(visitor), timeout=self._GRAPH_TIMEOUT
                )
            except asyncio.TimeoutError:
                logger.warning("ip_company_timeout", provider=label, visitor_id=visitor.visitor_id[:8])
                domain = None
                unavailable_detail = "timeout"
            except ProviderUnavailableError as exc:
                logger.warning("ip_company_unavailable", provider=label, error=str(exc))
                domain = None
                unavailable_detail = exc.detail or "provider unavailable"
            except (httpx.TransportError, httpx.HTTPStatusError) as exc:
                logger.warning("ip_company_error", provider=label, error=str(exc))
                domain = None
                unavailable_detail = safe_failure_detail(exc)
            except Exception as exc:
                # Our bug, not theirs — keep the lock (see _fetch above).
                logger.warning(
                    "ip_company_unexpected_error", provider=label, error=str(exc)
                )
                domain = None
            elapsed = int((time.monotonic() - start) * 1000)
            return (domain, elapsed, unavailable_detail)

        # "Attempted" means enabled AND holding a key. Both mixins return None
        # immediately when their key is empty, so gating the ledger on the enable
        # flag alone records a failed attempt for a provider that was never
        # called — which arms the 30-day retry lock and consumes a daily budget
        # slot over a config gap. `_resolve_identity_graphs_parallel` already
        # gates on key presence; this mirrors it.
        pdl_attempted = bool(
            settings.pdl_ip_enabled and settings.people_data_labs_api_key
        )
        ipinfo_attempted = bool(settings.ipinfo_enabled and settings.ipinfo_token)

        async def _fetch_pdl() -> tuple[str | None, int, str | None]:
            if not pdl_attempted:
                return (None, 0, None)
            return await _fetch_domain("pdl_ip", self._call_pdl_ip_enrich)

        async def _fetch_ipinfo() -> tuple[str | None, int, str | None]:
            if not ipinfo_attempted:
                return (None, 0, None)
            return await _fetch_domain("ipinfo", self._call_ipinfo_api)

        (pdl_domain, pdl_ms, pdl_detail), (ipi_domain, ipi_ms, ipi_detail) = (
            await asyncio.gather(_fetch_pdl(), _fetch_ipinfo())
        )

        # Only log providers we actually ran — a disabled or keyless provider was
        # never attempted, so it must not leave a "failed" row in the cost ledger.
        if pdl_attempted:
            pdl_cost = 0.01 if pdl_domain else 0.0
            await self._log_resolution(
                visitor,
                "pdl_ip_enrich",
                pdl_domain is not None,
                pdl_cost,
                pdl_ms,
                outcome=(
                    RESOLUTION_OUTCOME_PROVIDER_UNAVAILABLE if pdl_detail else None
                ),
                detail=pdl_detail,
            )
        if ipinfo_attempted:
            await self._log_resolution(
                visitor,
                "ipinfo",
                ipi_domain is not None,
                0.0,
                ipi_ms,
                outcome=(
                    RESOLUTION_OUTCOME_PROVIDER_UNAVAILABLE if ipi_detail else None
                ),
                detail=ipi_detail,
            )

        ip_attempted = int(pdl_attempted) + int(ipinfo_attempted)
        ip_unavailable = int(pdl_attempted and pdl_detail is not None) + int(
            ipinfo_attempted and ipi_detail is not None
        )
        verdict = tier_verdict(ip_attempted, ip_unavailable)

        domain = pdl_domain or ipi_domain
        if domain:
            logger.info(
                "ip_company_resolved",
                visitor_id=visitor.visitor_id[:8],
                domain=domain,
                source="pdl" if pdl_domain else "ipinfo",
            )
        return (domain, verdict)

    async def _redis_has_key(self, key: str) -> bool:
        """Return True if redis has the key (exists check). Non-fatal."""
        if not self.redis:
            return False
        try:
            return bool(await self.redis.exists(key))
        except Exception:
            return False

    # ──────────────────── Save + Log ────────────────────

    async def _save_identified(
        self,
        visitor: Visitor,
        data: dict,
        provider: str,
        source_agent_visit_id: str | None = None,
    ) -> IdentifiedVisitor | None:
        """Persist an IdentifiedVisitor row, handling concurrent-insert races.

        Validates email before saving. On UNIQUE constraint violation
        (same site_id + visitor_id already inserted by a concurrent request),
        roll back and return the pre-existing row.

        ``source_agent_visit_id`` (EvalLayer Phase 05, GUARD #1): the agent-origin
        marker. An explicit argument wins; otherwise it falls back to the value
        stashed on the resolver by ``resolve()`` for the in-flight call. It is set
        directly on the ``IdentifiedVisitor(...)`` constructor below so the marker
        is part of the SAME INSERT+COMMIT that creates the row — there is no
        window where an unmarked agent-derived row is durable. NULL for the human
        path (no arg, no active marker).
        """
        # Resolve the marker: explicit arg beats the in-flight resolve() state.
        agent_marker = (
            source_agent_visit_id
            if source_agent_visit_id is not None
            else getattr(self, "_active_source_agent_visit_id", None)
        )
        email = data.get("email")
        if email:
            # Normalize before any persistence: providers return mixed-case
            # addresses, while suppression (unsubscribe/bounce) and dedup
            # match on lowercase. Single choke point — every provider's
            # result passes through here.
            email = email.strip().lower()
            data["email"] = email
            from apps.api.services.email_validator import validate_email
            is_valid, reason = await validate_email(email)
            if not is_valid:
                logger.info(
                    "email_validation_failed",
                    visitor_id=visitor.visitor_id[:8],
                    reason=reason,
                    provider=provider,
                )
                data.pop("email", None)

        # Paid person-graphs: reject obvious name↔email corruption before save
        # (e.g. Janet Valla + danica_naluz@…). Owned/form paths are exempt —
        # the visitor typed the email themselves.
        if (
            provider in PAID_PERSON_GRAPH_PROVIDERS
            and data.get("email")
            and data.get("full_name")
            and not name_email_consistent(data.get("full_name"), data.get("email"))
        ):
            logger.info(
                "identity_rejected_name_email_mismatch",
                visitor_id=visitor.visitor_id[:8],
                provider=provider,
            )
            return None

        # Email dedup: if same (site_id, email) already identified under
        # a different visitor_id, link via canonical_visitor_id instead
        # of creating a duplicate IdentifiedVisitor row.
        if data.get("email"):
            existing_by_email = await self.db.execute(
                select(IdentifiedVisitor).where(
                    IdentifiedVisitor.site_id == visitor.site_id,
                    # lower() on the column too: rows saved before email
                    # normalization may be mixed case.
                    func.lower(IdentifiedVisitor.email) == data["email"],
                    IdentifiedVisitor.visitor_id != visitor.visitor_id,
                )
            )
            canonical = existing_by_email.scalar_one_or_none()
            if canonical:
                visitor.identity_status = "merged"
                visitor.canonical_visitor_id = canonical.visitor_id
                await self._log_owned_resolution(visitor, provider)
                try:
                    await self.db.commit()
                except Exception:
                    await self.db.rollback()
                logger.info(
                    "visitor_merged_by_email",
                    visitor_id=visitor.visitor_id[:8],
                    canonical_visitor_id=canonical.visitor_id[:8],
                )
                return canonical

        if not data.get("email") and not data.get("full_name"):
            logger.info("save_skipped_no_identity_data", visitor_id=visitor.visitor_id[:8])
            return None

        identified = IdentifiedVisitor(
            visitor_id=visitor.visitor_id,
            site_id=visitor.site_id,
            email=data.get("email"),
            full_name=data.get("full_name"),
            city=data.get("city"),
            region=data.get("region"),
            country=data.get("country"),
            resolution_provider=provider,
            confidence_score=data.get("confidence_score"),
            # GUARD #1: agent-origin marker written atomically with the row.
            source_agent_visit_id=agent_marker,
            # Ingest-abuse marker, copied from the visitor row in the SAME INSERT
            # so there is no window where an abuse-derived identity is durable and
            # unmarked. is_emailable_identity refuses any row carrying it.
            is_abuse_flagged=bool(getattr(visitor, "is_abuse_flagged", False)),
        )
        self.db.add(identified)
        # Identity-honesty Phase 1 (A1): a match sourced from an identity GRAPH is
        # a guess, not a confirmation — it lands on the candidate tier no matter
        # how high its confidence_score is. Only deterministic first-party signals
        # and human confirmation produce a flat "identified".
        visitor.identity_status = (
            "candidate" if is_graph_candidate_provider(provider) else "identified"
        )
        await self._log_owned_resolution(visitor, provider)
        # Read the ids off the instance BEFORE the commit attempt. rollback()
        # expires every instance in the session regardless of expire_on_commit,
        # so touching visitor.* inside the except branch would trigger a
        # synchronous lazy refresh and raise MissingGreenlet — losing the real
        # conflict behind an unrelated error.
        conflict_visitor_id = visitor.visitor_id
        conflict_site_id = visitor.site_id
        try:
            await self.db.commit()
        except IntegrityError:
            # Conflict on uq_identified_site_visitor. Two cases share this path:
            #   (a) a genuine concurrent-insert race, and
            #   (b) a RE-resolution of a visitor that already has a row (e.g.
            #       after reject-candidate returned them to anonymous).
            # Case (b) is why this can no longer just return the pre-existing row
            # unchanged: doing so left the visitor permanently stuck on the stale,
            # rejected data. Upsert semantics — overwrite the row with the fresh
            # result — are correct for both cases (in a true race the two results
            # are equivalent anyway).
            #
            # Deliberately an ORM update rather than a CORE
            # `INSERT ... ON CONFLICT DO UPDATE`: `identified_visitors` carries
            # before_insert/before_update PII-encryption hooks
            # (services/pii_encryption_hooks.py) that a CORE statement bypasses,
            # which would silently stop the *_ciphertext / email_bidx dual-write.
            # The ORM path keeps those hooks firing.
            #
            # Audit posture unchanged: `resolution_logs` is the immutable,
            # authoritative record of every resolution attempt; this row has
            # always been the mutable current-state projection.
            await self.db.rollback()
            logger.info(
                # devjulley's event name (the branch below is now upsert
                # semantics, not fetch-existing) with main's post-rollback-safe
                # variable: reading visitor.* here would lazy-refresh an expired
                # instance and raise MissingGreenlet.
                "save_identified_conflict_upsert",
                visitor_id=conflict_visitor_id[:8],
                provider=provider,
            )
            existing = await self.db.execute(
                select(IdentifiedVisitor).where(
                    IdentifiedVisitor.visitor_id == conflict_visitor_id,
                    IdentifiedVisitor.site_id == conflict_site_id,
                )
            )
            row = existing.scalar_one_or_none()
            if row is None:
                # Very unlikely: conflict resolved but row is gone — re-raise
                raise
            row.email = data.get("email")
            row.full_name = data.get("full_name")
            row.city = data.get("city")
            row.region = data.get("region")
            row.country = data.get("country")
            row.resolution_provider = provider
            row.confidence_score = data.get("confidence_score")
            # A fresh, successful re-resolution supersedes an earlier rejection.
            row.do_not_email = False
            visitor.identity_status = (
                "candidate" if is_graph_candidate_provider(provider) else "identified"
            )
            try:
                await self.db.commit()
            except Exception as exc:  # noqa: BLE001 — never crash resolve on this
                await self.db.rollback()
                logger.warning("save_identified_conflict_upsert_failed", error=str(exc))
            return row
        logger.info(
            "visitor_identified",
            visitor_id=visitor.visitor_id[:8],
            provider=provider,
            email=data.get("email", "")[:5] + "***" if data.get("email") else None,
        )

        # ── Beam Identity Network: contribute to cross-customer graph ──
        wrote_graph = await self._upsert_beam_identity(visitor, data, provider)
        # ── Identity co-op: credit only a graph write that really happened ──
        if wrote_graph and settings.identity_coop_enabled:
            from apps.api.services.identity_coop import maybe_record_contribution
            await maybe_record_contribution(self.db, visitor, data, provider)

        # ── Hot-visitor ping: email the owner if US + high-intent (best-effort) ──
        try:
            from apps.api.services.hot_alert import maybe_send_hot_alert

            await maybe_send_hot_alert(self.db, visitor, identified)
        except Exception as e:  # noqa: BLE001 — a failed ping must not break resolve
            logger.warning("hot_alert_failed", error=str(e))

        return identified

    async def _upsert_beam_identity(
        self, visitor: Visitor, data: dict, provider: str
    ) -> bool:
        """Write (fingerprint, email) to graph. True iff a row was really written."""
        fp = getattr(visitor, "fingerprint", None)
        email = data.get("email")
        if not fp or not email:
            return False
        # Write-boundary erasure guard. Enforced HERE, not only upstream: this
        # is the sole write path into the cross-tenant graph, so a person who
        # asked to be forgotten can never be silently re-added on a later visit
        # to any site. A no-op for everyone who has not opted out.
        from apps.api.services.graph_erasure import GRAPH_WRITE_BLOCKING_SCOPES
        from apps.api.services.suppression import is_email_suppressed_any

        if getattr(visitor, "do_not_resolve", False) or await is_email_suppressed_any(
            self.db, email, GRAPH_WRITE_BLOCKING_SCOPES
        ):
            logger.info(
                "graph_write_blocked", visitor_id=visitor.visitor_id[:8]
            )
            return False
        try:
            from sqlalchemy.dialects.postgresql import insert as pg_insert

            # Phase 05 (5b): dual-write encrypted columns. CORE insert → mapper
            # hooks don't fire; set ciphertext + blind index explicitly.
            from apps.api.services.pii_crypto import email_hash, encrypt_pii

            stmt = pg_insert(BeamIdentityNode).values(
                fingerprint=fp,
                fingerprint_v3=getattr(visitor, "fingerprint_v3", None),
                email=email,
                full_name=data.get("full_name"),
                email_ciphertext=encrypt_pii(email),
                email_bidx=email_hash(email),
                full_name_ciphertext=encrypt_pii(data.get("full_name")),
                confidence_score=data.get("confidence_score", 0.0),
                source_site_id=visitor.site_id,
                source_provider=provider,
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["fingerprint", "email"],
                set_={
                    # Backfill fp3 onto a row first written before fp3 existed,
                    # but never blank an existing value with a NULL from a visitor
                    # whose fp3 has not resolved yet.
                    "fingerprint_v3": func.coalesce(
                        stmt.excluded.fingerprint_v3, BeamIdentityNode.fingerprint_v3
                    ),
                    "full_name": stmt.excluded.full_name,
                    "full_name_ciphertext": stmt.excluded.full_name_ciphertext,
                    "confidence_score": stmt.excluded.confidence_score,
                    "source_provider": stmt.excluded.source_provider,
                    "updated_at": func.now(),
                },
            )
            await self.db.execute(stmt)
            await self.db.commit()
            logger.info(
                "beam_identity_upserted",
                fingerprint=fp[:12],
                email_domain=email.split("@")[-1],
            )
            return True
        except Exception as exc:
            await self.db.rollback()
            logger.debug("beam_identity_upsert_failed", error=str(exc))
            return False

    async def _graph_node_by_email(self, email: str) -> BeamIdentityNode | None:
        """Cross-customer graph lookup keyed on EMAIL (the email_bidx blind index).

        DETERMINISTIC and owned: if this exact email was already identified WITH a
        name on any Beam site, return that node so a freshly-captured email can
        inherit the name for free — no provider spend, stronger than a fingerprint
        guess. Reads the email_bidx column (`ix_beam_identity_graph_email_bidx`)
        the graph already writes on every upsert but never read until now."""
        if not email:
            return None
        try:
            from apps.api.services.pii_crypto import email_hash

            bidx = email_hash(email)
            return (
                await self.db.execute(
                    select(BeamIdentityNode)
                    .where(
                        BeamIdentityNode.email_bidx == bidx,
                        BeamIdentityNode.full_name.isnot(None),
                        BeamIdentityNode.confidence_score >= 0.5,
                    )
                    .order_by(BeamIdentityNode.confidence_score.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
        except Exception as exc:
            logger.debug("graph_email_lookup_failed", error=str(exc))
            return None

    async def _check_beam_identity_network(
        self, visitor: Visitor
    ) -> IdentifiedVisitor | None:
        """Check cross-customer identity graph by fingerprint.

        If this fingerprint was identified on ANY Beam site, reuse
        that identity (discounted confidence: 0.85).
        """
        fp = getattr(visitor, "fingerprint", None)
        fp_v3 = getattr(visitor, "fingerprint_v3", None)
        if not fp and not fp_v3:
            return None
        try:
            # Same v3-first, v2-fallback order as the per-site fingerprint match:
            # graph rows written before fp3 existed only carry the fp2 column.
            node = None
            for col, val in ((BeamIdentityNode.fingerprint_v3, fp_v3),
                             (BeamIdentityNode.fingerprint, fp)):
                if not val:
                    continue
                result = await self.db.execute(
                    select(BeamIdentityNode)
                    .where(
                        col == val,
                        BeamIdentityNode.email.isnot(None),
                        BeamIdentityNode.confidence_score >= 0.5,
                    )
                    .order_by(BeamIdentityNode.confidence_score.desc())
                    .limit(1)
                )
                node = result.scalar_one_or_none()
                if node:
                    break
            if node:
                logger.info(
                    "beam_identity_network_match",
                    visitor_id=visitor.visitor_id[:8],
                    source_site=node.source_site_id,
                    provider=node.source_provider,
                )
                return await self._save_identified(
                    visitor,
                    {
                        "email": node.email,
                        "full_name": node.full_name,
                        "confidence_score": 0.85,
                    },
                    "beam_identity_network",
                )
        except Exception as exc:
            logger.warning("beam_identity_check_failed", error=str(exc))
        return None

    async def _log_owned_resolution(self, visitor: Visitor, provider: str) -> None:
        """Write a cost=0 identity ledger row for an OWNED resolution.

        Paid providers already record their attempts via `_log_resolution`, but
        the free prior-signal paths (form_capture / fingerprint_match /
        beam_identity_network / svid_reconcile) never touched the ledger — so the
        owned-vs-paid coverage metric couldn't see them. This adds the row in the
        SAME transaction as the identity save (the caller commits). Best-effort:
        a logging hiccup must never break a successful identification."""
        from apps.api.services.identity_classification import OWNED_FREE_PROVIDERS

        if provider not in OWNED_FREE_PROVIDERS:
            return
        try:
            await log_api_call(
                db=self.db,
                site_id=visitor.site_id,
                visitor_id=visitor.visitor_id,
                provider=provider,
                category="identity",
                success=True,
                cost_usd=0.0,
                response_time_ms=0,
            )
        except Exception as exc:
            logger.debug("owned_resolution_log_failed", error=str(exc))

    async def _log_resolution(
        self,
        visitor: Visitor,
        provider: str,
        success: bool,
        cost: float,
        ms: int,
        *,
        outcome: str | None = None,
        detail: str | None = None,
    ) -> None:
        """Record one resolution attempt across both ledgers.

        `outcome` is the contract that separates "the provider answered, nobody
        matched" from "the provider never answered" — see RESOLUTION_OUTCOMES:

        - `match`                 — usable payload came back
        - `no_match`              — provider answered: 200-empty, 404, or 400
                                    (unresolvable IP). A real, informative answer.
        - `provider_unavailable`  — provider never answered: 401, 403, 429 after
                                    retries, 5xx, timeout, DNS or connect error.

        Only the first two write `ResolutionLog`. An outage is not an attempt, so
        counting it as one would arm the 30-day retry lock and burn the daily
        budget over a failure the visitor had nothing to do with. Every outcome
        still writes `api_usage_logs`, so outages stay observable rather than
        silently dropped; `price_for()` returns 0.0 when `success=False`, so those
        rows cannot distort the cost ledger.

        Keyword-only with a derived default so existing call sites keep their exact
        behavior — only callers that can actually tell an outage apart pass it.
        """
        if outcome is None:
            outcome = RESOLUTION_OUTCOME_MATCH if success else RESOLUTION_OUTCOME_NO_MATCH
        elif outcome not in RESOLUTION_OUTCOMES:
            # A typo must not silently become "not provider_unavailable" and
            # quietly re-arm the retry lock this whole change exists to remove.
            raise ValueError(
                f"unknown resolution outcome {outcome!r}; expected one of {sorted(RESOLUTION_OUTCOMES)}"
            )

        if outcome != RESOLUTION_OUTCOME_PROVIDER_UNAVAILABLE:
            log = ResolutionLog(
                site_id=visitor.site_id,
                visitor_id=visitor.visitor_id,
                provider=provider,
                success=success,
                cost_usd=cost,
                response_time_ms=ms,
            )
            self.db.add(log)
        else:
            logger.warning(
                "identity_provider_unavailable",
                provider=provider,
                visitor_id=visitor.visitor_id[:8],
                detail=(detail or "")[:200],
            )

        # Mirror into the unified cost ledger (api_usage_logs) so the costs
        # dashboard reads one source. resolution_logs stays the budget meter.
        # Best-effort — never breaks resolve; commits with the row below.
        meta = {"outcome": outcome}
        if detail:
            meta["detail"] = detail[:200]
        await log_api_call(
            db=self.db,
            site_id=visitor.site_id,
            visitor_id=visitor.visitor_id,
            provider=provider,
            category="identity",
            success=success,
            cost_usd=cost,
            response_time_ms=ms,
            meta=meta,
        )
        await self.db.commit()
