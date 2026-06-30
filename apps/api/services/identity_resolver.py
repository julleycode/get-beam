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

import structlog
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.config import settings
from apps.api.models.beam_identity import BeamIdentityNode
from apps.api.models.site import Site
from apps.api.models.visitor import IdentifiedVisitor, ResolutionLog, Visitor
from apps.api.services.usage_logger import log_api_call

# Re-exported for backward compatibility: callers and tests import these names
# from this module (e.g. `from ...identity_resolver import _url_to_host`, and
# `@patch("...identity_resolver.settings")`).
from apps.api.services.identity_providers.base import (  # noqa: F401
    REDIS_RESOLUTION_PREFIX,
    RESOLUTION_CACHE_TTL,
    _TRANSIENT_HTTP_STATUSES,
    HttpRetryMixin,
    _http_retry,
    _is_transient_http_error,
    _url_to_host,
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

    # ──────────────────── Pre-waterfall: Prior Signal Check ────────────────────

    async def _check_prior_signals(self, visitor: Visitor) -> IdentifiedVisitor | None:
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
        try:
            email_result = await self.db.execute(
                select(VisitorEmail.email)
                .where(
                    VisitorEmail.site_id == visitor.site_id,
                    VisitorEmail.visitor_id == visitor.visitor_id,
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
                # Save the captured email as a basic (owned) identification.
                return await self._save_identified(
                    visitor,
                    {
                        "email": captured_email,
                        "full_name": None,
                        "city": None,
                        "region": None,
                        "country": None,
                        "confidence_score": 0.80,
                    },
                    "form_capture",
                )
        except Exception as exc:
            logger.warning("prior_signal_email_check_failed", error=str(exc))

        # ── Check 2: Fingerprint match against already-identified visitors ──
        if getattr(visitor, "fingerprint", None):
            try:
                fp_result = await self.db.execute(
                    select(IdentifiedVisitor)
                    .join(Visitor, IdentifiedVisitor.visitor_id == Visitor.visitor_id)
                    .where(
                        Visitor.site_id == visitor.site_id,
                        Visitor.fingerprint == visitor.fingerprint,
                        Visitor.visitor_id != visitor.visitor_id,
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
                            "confidence_score": 0.75,  # slightly lower — fingerprint match
                        },
                        "fingerprint_match",
                    )
            except Exception as exc:
                logger.warning("prior_signal_fingerprint_check_failed", error=str(exc))

        # ── Check 3: Beam Identity Network (cross-customer graph) ──
        result = await self._check_beam_identity_network(visitor)
        if result:
            return result

        return None

    # ──────────────────── Main Waterfall ────────────────────

    async def resolve(self, visitor: Visitor) -> IdentifiedVisitor | None:
        """Identity resolution with parallel provider execution.

        Flow:
        -1. Pre-waterfall: captured emails + fingerprint matches
        0.  Identity Graphs (parallel): Leadpipe, Capturify, RB2B
        1-2. IP→Company (parallel): PDL + IPinfo
        3.  Hunter (domain → employee emails)
        4.  Apollo (domain → contact)
        """
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
        result = await self._check_prior_signals(visitor)
        if result:
            return result

        # ── Paid provider waterfall gates ──
        # The 30-day recency skip and daily budget only guard the PAID providers
        # below, not the free prior-signal path above.
        if await self.was_recently_attempted(visitor.site_id, visitor.visitor_id):
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

        # ── VPN/Proxy/Tor detection — skip expensive lookups for masked IPs ──
        if settings.ipinfo_token:
            try:
                from apps.api.services.company_resolver import check_ip_privacy, is_ip_suspicious
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

        result = await self._resolve_identity_graphs_parallel(visitor)
        if result:
            return result

        # ══════════════════════════════════════════════════════════════
        # Steps 1-2: IP → Company — PARALLEL fallback
        # PDL IP Enrich + IPinfo run concurrently. First domain wins.
        # ══════════════════════════════════════════════════════════════

        company_domain: str | None = None

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
            company_domain = await self._resolve_ip_company_parallel(visitor)

            # ── Cache the result (hit or miss) ──
            if self.redis:
                try:
                    if company_domain:
                        await self.redis.setex(cache_key, RESOLUTION_CACHE_TTL, company_domain)
                    else:
                        await self.redis.setex(cache_key, 86400, "__none__")
                except Exception:
                    pass

        if company_domain:
            # Store company domain on visitor for future use
            visitor.company_domain = company_domain
            await self.db.commit()

            # ── Step 3: Hunter (domain → employee emails) ──
            result = await self._try_hunter_domain(visitor, company_domain)
            if result:
                return result

            # ── Step 4: Apollo (domain → contact lookup) ──
            result = await self._try_apollo(visitor, company_domain)
            if result:
                return result

        # No match from any provider
        visitor.identity_status = "unresolvable"
        await self.db.commit()
        return None

    # ──────────────────── Parallel Orchestrators ────────────────────

    _GRAPH_TIMEOUT = 5.0  # seconds per identity graph provider

    async def _resolve_identity_graphs_parallel(
        self, visitor: Visitor
    ) -> IdentifiedVisitor | None:
        """Run Leadpipe, Capturify, RB2B in parallel. Save first match."""

        # A disabled provider passes a None key, so the existing `if not api_key`
        # guard below skips it cleanly — same path as a missing key.
        providers = [
            ("leadpipe", settings.leadpipe_api_key if settings.leadpipe_enabled else None, self._call_leadpipe_api, 0.0),
            ("capturify", settings.capturify_api_key if settings.capturify_enabled else None, self._call_capturify_api, 0.0),
            ("rb2b", settings.rb2b_api_key if settings.rb2b_enabled else None, self._call_rb2b_api, 0.09),
        ]

        async def _fetch(
            name: str, api_key: str | None, call_fn
        ) -> tuple[str, dict | None, int, bool]:
            if not api_key:
                return (name, None, 0, False)
            start = time.monotonic()
            try:
                data = await asyncio.wait_for(
                    call_fn(visitor), timeout=self._GRAPH_TIMEOUT
                )
            except asyncio.TimeoutError:
                logger.warning(
                    "identity_graph_timeout",
                    provider=name,
                    visitor_id=visitor.visitor_id[:8],
                )
                data = None
            except Exception as exc:
                logger.warning(
                    "identity_graph_error",
                    provider=name,
                    error=str(exc),
                    visitor_id=visitor.visitor_id[:8],
                )
                data = None
            elapsed = int((time.monotonic() - start) * 1000)
            return (name, data, elapsed, True)

        results = await asyncio.gather(
            *[_fetch(n, k, c) for n, k, c, _ in providers],
            return_exceptions=True,
        )

        best_name: str | None = None
        best_data: dict | None = None

        for i, r in enumerate(results):
            if isinstance(r, BaseException):
                logger.warning(
                    "identity_graph_gather_exc",
                    provider=providers[i][0],
                    error=str(r),
                )
                continue
            name, data, elapsed, attempted = r
            if not attempted:
                continue
            success_cost = providers[i][3] if data else 0.0
            await self._log_resolution(
                visitor, name, data is not None, success_cost, elapsed
            )
            if data and best_data is None:
                best_name = name
                best_data = data

        if best_data and best_name:
            logger.info(
                "identity_graph_identified",
                provider=best_name,
                visitor_id=visitor.visitor_id[:8],
                email=(best_data.get("email", "")[:5] + "***"
                       if best_data.get("email") else None),
            )
            return await self._save_identified(visitor, best_data, best_name)

        return None

    async def _resolve_ip_company_parallel(self, visitor: Visitor) -> str | None:
        """Run PDL IP Enrich + IPinfo in parallel. Return first domain."""

        async def _fetch_pdl() -> tuple[str | None, int]:
            if not settings.pdl_ip_enabled:
                return (None, 0)
            start = time.monotonic()
            try:
                domain = await asyncio.wait_for(
                    self._call_pdl_ip_enrich(visitor),
                    timeout=self._GRAPH_TIMEOUT,
                )
            except asyncio.TimeoutError:
                logger.warning("pdl_ip_timeout", visitor_id=visitor.visitor_id[:8])
                domain = None
            except Exception as exc:
                logger.warning("pdl_ip_error", error=str(exc))
                domain = None
            elapsed = int((time.monotonic() - start) * 1000)
            return (domain, elapsed)

        async def _fetch_ipinfo() -> tuple[str | None, int]:
            if not settings.ipinfo_enabled:
                return (None, 0)
            start = time.monotonic()
            try:
                domain = await asyncio.wait_for(
                    self._call_ipinfo_api(visitor),
                    timeout=self._GRAPH_TIMEOUT,
                )
            except asyncio.TimeoutError:
                logger.warning("ipinfo_timeout", visitor_id=visitor.visitor_id[:8])
                domain = None
            except Exception as exc:
                logger.warning("ipinfo_error", error=str(exc))
                domain = None
            elapsed = int((time.monotonic() - start) * 1000)
            return (domain, elapsed)

        (pdl_domain, pdl_ms), (ipi_domain, ipi_ms) = await asyncio.gather(
            _fetch_pdl(), _fetch_ipinfo()
        )

        # Only log providers we actually ran — a disabled provider was never
        # attempted, so it must not leave a "failed" row in the cost ledger.
        if settings.pdl_ip_enabled:
            pdl_cost = 0.01 if pdl_domain else 0.0
            await self._log_resolution(
                visitor, "pdl_ip_enrich", pdl_domain is not None, pdl_cost, pdl_ms
            )
        if settings.ipinfo_enabled:
            await self._log_resolution(
                visitor, "ipinfo", ipi_domain is not None, 0.0, ipi_ms
            )

        domain = pdl_domain or ipi_domain
        if domain:
            logger.info(
                "ip_company_resolved",
                visitor_id=visitor.visitor_id[:8],
                domain=domain,
                source="pdl" if pdl_domain else "ipinfo",
            )
        return domain

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
        self, visitor: Visitor, data: dict, provider: str
    ) -> IdentifiedVisitor | None:
        """Persist an IdentifiedVisitor row, handling concurrent-insert races.

        Validates email before saving. On UNIQUE constraint violation
        (same site_id + visitor_id already inserted by a concurrent request),
        roll back and return the pre-existing row.
        """
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
        )
        self.db.add(identified)
        visitor.identity_status = "identified"
        await self._log_owned_resolution(visitor, provider)
        try:
            await self.db.commit()
        except IntegrityError:
            # A concurrent resolution already inserted this visitor — roll back
            # and fetch the existing record instead of crashing.
            await self.db.rollback()
            logger.info(
                "save_identified_conflict_fetch_existing",
                visitor_id=visitor.visitor_id[:8],
                provider=provider,
            )
            existing = await self.db.execute(
                select(IdentifiedVisitor).where(
                    IdentifiedVisitor.visitor_id == visitor.visitor_id,
                    IdentifiedVisitor.site_id == visitor.site_id,
                )
            )
            row = existing.scalar_one_or_none()
            if row is None:
                # Very unlikely: conflict resolved but row is gone — re-raise
                raise
            return row
        logger.info(
            "visitor_identified",
            visitor_id=visitor.visitor_id[:8],
            provider=provider,
            email=data.get("email", "")[:5] + "***" if data.get("email") else None,
        )

        # ── Beam Identity Network: contribute to cross-customer graph ──
        await self._upsert_beam_identity(visitor, data, provider)

        # ── Hot-visitor ping: email the owner if US + high-intent (best-effort) ──
        try:
            from apps.api.services.hot_alert import maybe_send_hot_alert

            await maybe_send_hot_alert(self.db, visitor, identified)
        except Exception as e:  # noqa: BLE001 — a failed ping must not break resolve
            logger.warning("hot_alert_failed", error=str(e))

        return identified

    async def _upsert_beam_identity(
        self, visitor: Visitor, data: dict, provider: str
    ) -> None:
        """Write (fingerprint, email) to cross-customer identity graph."""
        fp = getattr(visitor, "fingerprint", None)
        email = data.get("email")
        if not fp or not email:
            return
        try:
            from sqlalchemy.dialects.postgresql import insert as pg_insert

            # Phase 05 (5b): dual-write encrypted columns. CORE insert → mapper
            # hooks don't fire; set ciphertext + blind index explicitly.
            from apps.api.services.pii_crypto import email_hash, encrypt_pii

            stmt = pg_insert(BeamIdentityNode).values(
                fingerprint=fp,
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
        except Exception as exc:
            await self.db.rollback()
            logger.debug("beam_identity_upsert_failed", error=str(exc))

    async def _check_beam_identity_network(
        self, visitor: Visitor
    ) -> IdentifiedVisitor | None:
        """Check cross-customer identity graph by fingerprint.

        If this fingerprint was identified on ANY Beam site, reuse
        that identity (discounted confidence: 0.85).
        """
        fp = getattr(visitor, "fingerprint", None)
        if not fp:
            return None
        try:
            result = await self.db.execute(
                select(BeamIdentityNode)
                .where(
                    BeamIdentityNode.fingerprint == fp,
                    BeamIdentityNode.email.isnot(None),
                    BeamIdentityNode.confidence_score >= 0.5,
                )
                .order_by(BeamIdentityNode.confidence_score.desc())
                .limit(1)
            )
            node = result.scalar_one_or_none()
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
        self, visitor: Visitor, provider: str, success: bool, cost: float, ms: int
    ) -> None:
        log = ResolutionLog(
            site_id=visitor.site_id,
            visitor_id=visitor.visitor_id,
            provider=provider,
            success=success,
            cost_usd=cost,
            response_time_ms=ms,
        )
        self.db.add(log)
        # Mirror into the unified cost ledger (api_usage_logs) so the costs
        # dashboard reads one source. resolution_logs stays the budget meter.
        # Best-effort — never breaks resolve; commits with the row below.
        await log_api_call(
            db=self.db,
            site_id=visitor.site_id,
            visitor_id=visitor.visitor_id,
            provider=provider,
            category="identity",
            success=success,
            cost_usd=cost,
            response_time_ms=ms,
        )
        await self.db.commit()
