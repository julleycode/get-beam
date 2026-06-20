"""Clay-style identity resolution with parallel provider execution.

Identity graphs (Leadpipe, Capturify, RB2B) run in parallel via
asyncio.gather — first match wins. If none match, IP→Company
providers (PDL + IPinfo) also run in parallel, then feed Hunter/Apollo
sequentially for person-level enrichment.

Providers:
  Identity Graphs (parallel): Leadpipe ~35%, Capturify ~40%, RB2B ~30%
  IP → Company (parallel):    PDL ~30-40%, IPinfo ~20-30%
  Company → Person (seq):     Hunter ~50%, Apollo ~40%
"""

import asyncio
import socket
import time
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

import httpx
import structlog
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception

from apps.api.config import settings
from apps.api.models.beam_identity import BeamIdentityNode
from apps.api.models.site import Site
from apps.api.models.visitor import IdentifiedVisitor, ResolutionLog, Visitor
from apps.api.services.usage_logger import log_api_call

logger = structlog.get_logger()

REDIS_RESOLUTION_PREFIX = "resolution:"
RESOLUTION_CACHE_TTL = 30 * 86400  # 30 days

# Transient HTTP errors worth retrying (timeouts, rate limits, 5xx server errors).
# 4xx client errors (400, 401, 403, 404) are NOT transient — never retry those.
_TRANSIENT_HTTP_STATUSES = {429, 500, 502, 503, 504}


def _is_transient_http_error(exc: BaseException) -> bool:
    """Return True for retryable httpx errors (timeouts, connection errors, 5xx/429)."""
    if isinstance(exc, httpx.TimeoutException):
        return True
    if isinstance(exc, httpx.ConnectError):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in _TRANSIENT_HTTP_STATUSES
    return False


# Retry decorator for external HTTP calls.
# Retries up to 3 attempts (including the first) with exponential backoff 1→2→8s.
_http_retry = retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    retry=retry_if_exception(_is_transient_http_error),
    reraise=True,
)


def _url_to_host(url: str | None) -> str | None:
    """Bare hostname from a site URL ('https://www.grade.coach/x' -> 'grade.coach').

    Used to scope provider queries to one site's pixel domain.
    """
    if not url:
        return None
    host = urlparse(url if "//" in url else f"//{url}").hostname
    if host and host.startswith("www."):
        host = host[4:]
    return host


class IdentityResolver:
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

    # ──────────────────── Pre-waterfall: Prior Signal Check ────────────────────

    async def _check_prior_signals(self, visitor: Visitor) -> IdentifiedVisitor | None:
        """Check for existing identification signals BEFORE the IP waterfall.

        Two checks (in order):
        1. visitor_emails table — if this visitor_id has a captured email,
           use it to enrich directly via PDL (no IP credit needed).
        2. Fingerprint match — if another visitor with the same browser fingerprint
           was already identified, copy their identity to this visitor.

        Returns an IdentifiedVisitor if a signal produces a match, else None.
        """
        from apps.api.models.visitor_email import VisitorEmail

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
                # Enrich the email directly with PDL
                enriched = await self._enrich_email_pdl(visitor, captured_email)
                if enriched:
                    return enriched
                # If PDL can't enrich it, still save the email as a basic identification
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

    async def _enrich_email_pdl(
        self, visitor: Visitor, email: str
    ) -> IdentifiedVisitor | None:
        """Use PDL person enrich to get profile data from a known email address."""
        if not settings.people_data_labs_api_key:
            return None

        start = time.monotonic()
        data: dict | None = None
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    "https://api.peopledatalabs.com/v5/person/enrich",
                    headers={"X-Api-Key": settings.people_data_labs_api_key},
                    params={"email": email, "pretty": "false"},
                )
                if resp.status_code == 200:
                    body = resp.json()
                    person = body.get("data", {}) or {}
                    if person:
                        data = {
                            "email": email,
                            "full_name": person.get("full_name"),
                            "city": (person.get("location_names") or [None])[0],
                            "region": person.get("location_region"),
                            "country": person.get("location_country"),
                            "confidence_score": 0.90,
                        }
                elif resp.status_code == 404:
                    logger.debug("pdl_person_enrich_no_match", email_domain=email.split("@")[-1])
                else:
                    logger.warning("pdl_person_enrich_error", status=resp.status_code)
        except Exception as exc:
            logger.warning("pdl_person_enrich_exception", error=str(exc))

        elapsed_ms = int((time.monotonic() - start) * 1000)
        await self._log_resolution(visitor, "pdl_person_enrich", data is not None, 0.01 if data else 0.0, elapsed_ms)

        if data:
            return await self._save_identified(visitor, data, "pdl_person_enrich")
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

        providers = [
            ("leadpipe", settings.leadpipe_api_key, self._call_leadpipe_api, 0.0),
            ("capturify", settings.capturify_api_key, self._call_capturify_api, 0.0),
            ("rb2b", settings.rb2b_api_key, self._call_rb2b_api, 0.09),
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

        pdl_cost = 0.01 if pdl_domain else 0.0
        await self._log_resolution(
            visitor, "pdl_ip_enrich", pdl_domain is not None, pdl_cost, pdl_ms
        )
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

    # ──────────────── Helper: Identity-graph record matching ────────────────

    # A provider record may only be attached to a visitor when its IP matches
    # AND it was captured within this window of the visitor's own activity.
    # Identity-graph feeds are account-wide (latest N identifications across
    # ALL traffic), so bare IP equality risks attaching the wrong human —
    # e.g. CGNAT/office IPs shared by many people across hours or days.
    _IDENTITY_MATCH_WINDOW = timedelta(minutes=30)

    # Field-name variants providers use for the record capture timestamp
    # (same flexible-variant style as the ip/ipAddress/ip_address handling).
    _RECORD_TIMESTAMP_FIELDS = (
        "timestamp",
        "capturedAt",
        "captured_at",
        "createdAt",
        "created_at",
        "identifiedAt",
        "identified_at",
        "lastSeen",
        "last_seen",
        "seenAt",
        "seen_at",
        "visitedAt",
        "visited_at",
        "date",
    )

    @classmethod
    def _parse_record_timestamp(cls, record: dict) -> datetime | None:
        """Best-effort parse of an identification record's capture time (UTC).

        Accepts ISO-8601 strings (with or without 'Z'/offset) and epoch
        seconds/milliseconds. Returns a timezone-aware UTC datetime, or None
        when no usable timestamp field exists on the record.
        """
        for field in cls._RECORD_TIMESTAMP_FIELDS:
            raw = record.get(field)
            if raw is None or isinstance(raw, bool):
                continue
            if isinstance(raw, (int, float)):
                ts = float(raw)
                if ts > 1e12:  # epoch milliseconds
                    ts /= 1000.0
                try:
                    return datetime.fromtimestamp(ts, tz=timezone.utc)
                except (OverflowError, OSError, ValueError):
                    continue
            if isinstance(raw, str) and raw.strip():
                try:
                    parsed = datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
                except ValueError:
                    continue
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                return parsed.astimezone(timezone.utc)
        return None

    @staticmethod
    def _visitor_activity_utc(visitor: Visitor) -> datetime:
        """The visitor's most recent activity as an aware UTC datetime.

        Visitor.last_seen is stored naive-UTC; fall back to "now" if missing.
        """
        last_seen = getattr(visitor, "last_seen", None)
        if isinstance(last_seen, datetime):
            if last_seen.tzinfo is None:
                return last_seen.replace(tzinfo=timezone.utc)
            return last_seen.astimezone(timezone.utc)
        return datetime.now(timezone.utc)

    def _record_matches_visitor(
        self, record: dict, visitor: Visitor, provider: str
    ) -> tuple[bool, bool]:
        """Decide whether an identity-graph record belongs to this visitor.

        Returns (matched, weak):
          - (False, False): record is not this visitor (IP mismatch, or
            timestamped outside the recency window) — caller must skip it.
          - (True, False):  IP matches AND record timestamp is within
            _IDENTITY_MATCH_WINDOW of the visitor's activity — strong match.
          - (True, True):   IP matches but the record has no usable timestamp —
            weak evidence; caller must cap confidence at <= 0.6.
        """
        record_ts = self._parse_record_timestamp(record)
        if record_ts is None:
            logger.warning(
                "weak_ip_only_match",
                provider=provider,
                visitor_id=visitor.visitor_id[:8],
                detail="record has no usable timestamp; IP equality only",
            )
            return (True, True)

        delta = abs(record_ts - self._visitor_activity_utc(visitor))
        if delta > self._IDENTITY_MATCH_WINDOW:
            logger.debug(
                "identity_graph_record_outside_window",
                provider=provider,
                visitor_id=visitor.visitor_id[:8],
                delta_minutes=int(delta.total_seconds() // 60),
            )
            return (False, False)
        return (True, False)

    # Confidence ceiling for IP-only matches (no record timestamp available)
    _WEAK_MATCH_MAX_CONFIDENCE = 0.6

    # ──────────────────── Provider: Leadpipe Identity Graph ────────────────────

    LEADPIPE_API_BASE = "https://api.aws53.cloud"

    async def _try_leadpipe_identify(self, visitor: Visitor) -> IdentifiedVisitor | None:
        """Leadpipe Identity Graph: pixel-based person identification.

        Leadpipe's JS pixel (installed alongside Beam's pixel) captures
        browser signals and matches them against a 280M+ person graph.
        We poll their API for identified visitors matching this visitor's
        page URL + timestamp window.
        """
        if not settings.leadpipe_api_key:
            return None

        start = time.monotonic()

        data = await self._call_leadpipe_api(visitor)
        success = data is not None

        elapsed_ms = int((time.monotonic() - start) * 1000)
        cost = 0.0  # Free trial (500 IDs)
        await self._log_resolution(visitor, "leadpipe", success, cost, elapsed_ms)

        if data:
            logger.info(
                "leadpipe_person_identified",
                visitor_id=visitor.visitor_id[:8],
                email=data.get("email", "")[:5] + "***" if data.get("email") else None,
            )
            return await self._save_identified(visitor, data, "leadpipe")
        return None

    @_http_retry
    async def _call_leadpipe_api(self, visitor: Visitor) -> dict | None:
        """Query Leadpipe for identified visitors matching this visitor's session.

        Match logic: Look for Leadpipe identifications from the same IP
        within a short time window of the visitor's last_seen timestamp.
        Retries up to 3× on transient errors (5xx, 429, timeouts).
        """
        async with httpx.AsyncClient(timeout=15.0) as client:
            # Scope to THIS site's pixel domain. /v1/data is account-wide and
            # paginates at 50/page; without scoping, a low-traffic site's record
            # is buried under other sites' identifications and never seen. The
            # API has NO per-IP or per-pixel filter (only email/page/timeframe/
            # domain), so `domain` is the only documented way to narrow it.
            # (limit/sort sent previously were not real params — ignored.)
            # Falls back to the account-wide feed when the site URL is unknown.
            params: dict[str, str] = {}
            site_domain = await self._site_domain(visitor.site_id)
            if site_domain:
                params["domain"] = site_domain
            resp = await client.get(
                f"{self.LEADPIPE_API_BASE}/v1/data",
                headers={"X-API-Key": settings.leadpipe_api_key},
                params=params,
            )

            if resp.status_code == 404:
                logger.debug("leadpipe_no_matches")
                return None
            if resp.status_code != 200:
                logger.warning("leadpipe_api_error", status=resp.status_code,
                               detail=resp.text[:200])
                self._raise_if_transient(resp)
                return None

            body = resp.json()

            # TEMP shape probe — REMOVE once a real prod response confirms the
            # schema. /v1/data's response is undocumented; the parser below
            # assumes data[].{ip,email,...}. Log STRUCTURE ONLY (key names, never
            # values → no PII) so we can verify the parser reads the right fields
            # the next time Leadpipe runs on US traffic.
            try:
                if isinstance(body, dict):
                    top_keys = sorted(body.keys())
                    sample = body.get("data") or body.get("visitors") or body.get("results")
                elif isinstance(body, list):
                    top_keys, sample = "<list>", body
                else:
                    top_keys, sample = f"<{type(body).__name__}>", None
                record_keys = (
                    sorted(sample[0].keys())
                    if isinstance(sample, list) and sample and isinstance(sample[0], dict)
                    else None
                )
                logger.info(
                    "leadpipe_response_shape", top_level=top_keys, record_keys=record_keys
                )
            except Exception:
                pass

            visitors_data = body.get("data", []) if isinstance(body, dict) else []

            if not visitors_data:
                logger.debug("leadpipe_no_matches")
                return None

            # Even scoped to this site's domain the feed holds many visitors, so
            # a record only attaches to THIS visitor on IP equality AND recency
            # (_record_matches_visitor). The old "page URL contains site domain"
            # fallback attached arbitrary humans and is intentionally gone.
            for lp_visitor in visitors_data:
                lp_email = lp_visitor.get("email")
                if not lp_email and isinstance(lp_visitor.get("emails"), list) and lp_visitor.get("emails"):
                    lp_email = lp_visitor["emails"][0]
                if not lp_email:
                    continue

                lp_ip = lp_visitor.get("ip") or lp_visitor.get("ipAddress")
                if not lp_ip or lp_ip != visitor.ip_address:
                    continue

                matched, weak = self._record_matches_visitor(
                    lp_visitor, visitor, "leadpipe"
                )
                if not matched:
                    continue

                person = self._parse_leadpipe_person(lp_visitor)
                if weak:
                    person["confidence_score"] = min(
                        person["confidence_score"], self._WEAK_MATCH_MAX_CONFIDENCE
                    )
                return person

            logger.debug("leadpipe_no_ip_match", ip=visitor.ip_address[:8])
            return None

    @staticmethod
    def _parse_leadpipe_person(lp: dict) -> dict:
        """Parse Leadpipe visitor record into our standard format."""
        email = lp.get("email")
        if not email and isinstance(lp.get("emails"), list) and lp["emails"]:
            email = lp["emails"][0]

        name = lp.get("name") or lp.get("fullName")
        if not name:
            first = lp.get("firstName", "")
            last = lp.get("lastName", "")
            name = f"{first} {last}".strip() or None

        return {
            "email": email,
            "full_name": name,
            "city": lp.get("city"),
            "region": lp.get("state") or lp.get("region"),
            "country": lp.get("country"),
            "confidence_score": 0.95,  # Identity graph = high confidence
        }

    # ──────────────────── Provider: Capturify Identity Graph ────────────────────

    CAPTURIFY_API_BASE = "https://api.capturify.io"

    async def _try_capturify_identify(self, visitor: Visitor) -> IdentifiedVisitor | None:
        """Capturify Identity Graph: pixel-based person identification.

        Capturify's JS pixel captures browser signals and matches against
        their identity graph. Claims ~60% match rate. API key required.
        """
        if not settings.capturify_api_key:
            return None

        start = time.monotonic()

        data = await self._call_capturify_api(visitor)
        success = data is not None

        elapsed_ms = int((time.monotonic() - start) * 1000)
        cost = 0.0  # Free trial (500 leads)
        await self._log_resolution(visitor, "capturify", success, cost, elapsed_ms)

        if data:
            logger.info(
                "capturify_person_identified",
                visitor_id=visitor.visitor_id[:8],
                email=data.get("email", "")[:5] + "***" if data.get("email") else None,
            )
            return await self._save_identified(visitor, data, "capturify")
        return None

    @_http_retry
    async def _call_capturify_api(self, visitor: Visitor) -> dict | None:
        """Query Capturify for identified visitors matching this visitor.

        Uses the same pattern as Leadpipe: query recent identifications,
        match by IP address, parse person data.
        Retries up to 3× on transient errors (5xx, 429, timeouts).
        """
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"{self.CAPTURIFY_API_BASE}/v1/visitors",
                headers={"Authorization": f"Bearer {settings.capturify_api_key}"},
                params={
                    "limit": 10,
                    "sort": "desc",
                },
            )

            if resp.status_code == 401:
                logger.warning("capturify_unauthorized", detail="Check CAPTURIFY_API_KEY")
                return None
            if resp.status_code == 404:
                logger.debug("capturify_no_matches")
                return None
            if resp.status_code != 200:
                logger.warning("capturify_api_error", status=resp.status_code,
                               detail=resp.text[:200])
                self._raise_if_transient(resp)
                return None

            body = resp.json()
            # Capturify may return {"data": [...]} or {"visitors": [...]} or a bare list
            visitors_data = (
                body.get("data")
                or body.get("visitors")
                or (body if isinstance(body, list) else [])
            )

            if not visitors_data:
                logger.debug("capturify_empty_response")
                return None

            # Account-wide feed: require IP equality AND recency, same as
            # Leadpipe (see _record_matches_visitor).
            for cap_visitor in visitors_data:
                cap_ip = (
                    cap_visitor.get("ip")
                    or cap_visitor.get("ipAddress")
                    or cap_visitor.get("ip_address")
                )
                if not cap_ip or cap_ip != visitor.ip_address:
                    continue

                matched, weak = self._record_matches_visitor(
                    cap_visitor, visitor, "capturify"
                )
                if not matched:
                    continue

                person = self._parse_capturify_person(cap_visitor)
                if weak:
                    person["confidence_score"] = min(
                        person["confidence_score"], self._WEAK_MATCH_MAX_CONFIDENCE
                    )
                return person

            logger.debug("capturify_no_ip_match", ip=visitor.ip_address[:8])
            return None

    @staticmethod
    def _parse_capturify_person(cap: dict) -> dict:
        """Parse Capturify visitor record into our standard format.

        Capturify's response shape may differ from Leadpipe's; we handle
        common field name variants flexibly.
        """
        email = cap.get("email")
        if not email and isinstance(cap.get("emails"), list) and cap["emails"]:
            email = cap["emails"][0]

        name = cap.get("name") or cap.get("fullName") or cap.get("full_name")
        if not name:
            first = cap.get("firstName") or cap.get("first_name", "")
            last = cap.get("lastName") or cap.get("last_name", "")
            name = f"{first} {last}".strip() or None

        return {
            "email": email,
            "full_name": name,
            "city": cap.get("city"),
            "region": cap.get("state") or cap.get("region"),
            "country": cap.get("country"),
            "confidence_score": 0.90,  # Identity graph = high confidence
        }

    # ──────────────────── Provider: RB2B Identity Graph ────────────────────

    async def _try_rb2b_identify(self, visitor: Visitor) -> IdentifiedVisitor | None:
        """RB2B Identity Graph: IP → hashed email → person profile.

        This is TRUE person-level identification via cookie/device graph.
        Works even for residential IPs if the person is in RB2B's network.
        US traffic only. Returns actual visitor's email, not a company employee.
        """
        if not settings.rb2b_api_key:
            return None

        start = time.monotonic()

        data = await self._call_rb2b_api(visitor)
        success = data is not None

        elapsed_ms = int((time.monotonic() - start) * 1000)
        cost = 0.09 if success else 0.0
        await self._log_resolution(visitor, "rb2b_identity_graph", success, cost, elapsed_ms)

        if data:
            logger.info(
                "rb2b_person_identified",
                visitor_id=visitor.visitor_id[:8],
                email=data.get("email", "")[:5] + "***" if data.get("email") else None,
            )
            return await self._save_identified(visitor, data, "rb2b")
        return None

    @_http_retry
    async def _call_rb2b_api(self, visitor: Visitor) -> dict | None:
        """Call RB2B API Suite: IP to HEM → HEM to Business Profile.

        Two-step chain (api.rb2b.com/api/v1/):
        1. ip_to_hem: IP → Hashed Email (md5/sha256 + score)
        2. hem_to_business_profile: HEM → Full business profile
        Auth: Api-Key header. Retries up to 3× on transient errors.
        """
        rb2b_headers = {
            "Api-Key": settings.rb2b_api_key,
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=15.0) as client:
            # Step 1: IP → Hashed Email Match (HEM)
            resp = await client.post(
                "https://api.rb2b.com/api/v1/ip_to_hem",
                headers=rb2b_headers,
                json={
                    "ip_address": visitor.ip_address,
                    "user_agent": getattr(visitor, "user_agent", "") or "",
                    "include_sha256": True,
                },
            )

            if resp.status_code == 404:
                logger.debug("rb2b_no_match", ip=visitor.ip_address[:8])
                return None
            if resp.status_code == 403:
                logger.warning("rb2b_service_unavailable", detail=resp.text[:200])
                return None
            if resp.status_code != 200:
                logger.warning("rb2b_ip_error", status=resp.status_code,
                               detail=resp.text[:200])
                self._raise_if_transient(resp)
                return None

            hem_data = resp.json()
            results = hem_data.get("results", [])
            if not results:
                logger.debug("rb2b_no_hem", ip=visitor.ip_address[:8])
                return None

            best = max(results, key=lambda r: r.get("score", 0))
            hem = best.get("md5") or best.get("sha256")
            if not hem:
                logger.debug("rb2b_no_hem_hash", ip=visitor.ip_address[:8])
                return None

            # Step 2: HEM → Business Profile
            profile_resp = await client.post(
                "https://api.rb2b.com/api/v1/hem_to_business_profile",
                headers=rb2b_headers,
                json={"md5": hem},
            )

            if profile_resp.status_code != 200:
                logger.warning("rb2b_profile_error", status=profile_resp.status_code)
                self._raise_if_transient(profile_resp)
                return None

            profile = profile_resp.json()
            person = profile.get("result", profile)

            personal_emails = person.get("personal_emails") or []
            work_email = person.get("work_email")
            email = work_email or (personal_emails[0] if personal_emails else None)
            if not email:
                logger.debug("rb2b_no_email_in_profile", ip=visitor.ip_address[:8])
                return None

            # RB2B scores arrive on a 0-100 scale; ours is 0-1. Without the
            # normalization any score > 1 pinned the confidence to 0.99.
            raw_score = best.get("score", 0.9)
            if isinstance(raw_score, (int, float)) and raw_score > 1:
                raw_score = raw_score / 100.0
            return {
                "email": email,
                "full_name": person.get("full_name"),
                "title": person.get("current_title"),
                "company": person.get("current_company"),
                "linkedin_url": person.get("linkedin_url"),
                "city": person.get("city"),
                "region": person.get("state") or person.get("region"),
                "country": person.get("country", "US"),
                "confidence_score": max(0.0, min(float(raw_score), 0.99)),
            }

    async def _redis_has_key(self, key: str) -> bool:
        """Return True if redis has the key (exists check). Non-fatal."""
        if not self.redis:
            return False
        try:
            return bool(await self.redis.exists(key))
        except Exception:
            return False

    # ──────────────────── Provider: PDL IP Enrich ────────────────────

    async def _try_pdl_ip_enrich(self, visitor: Visitor) -> str | None:
        """PDL IP Enrichment: IP → company domain + location.

        Returns company domain string (feeds into Hunter/Apollo), or None.
        Also stores location data on visitor if available.
        """
        start = time.monotonic()

        domain = await self._call_pdl_ip_enrich(visitor)
        success = domain is not None

        elapsed_ms = int((time.monotonic() - start) * 1000)
        cost = 0.01 if success else 0.0
        await self._log_resolution(visitor, "pdl_ip_enrich", success, cost, elapsed_ms)

        if domain:
            logger.info("pdl_ip_company_found", visitor_id=visitor.visitor_id[:8], domain=domain)
        return domain

    @staticmethod
    def _raise_if_transient(resp: httpx.Response) -> None:
        """Raise HTTPStatusError for transient statuses so tenacity can retry them.

        Intentionally does NOT raise for 400 (bad request / unresolvable IP) or
        404 (no match) — those are legitimate "no result" responses.
        """
        if resp.status_code in _TRANSIENT_HTTP_STATUSES:
            resp.raise_for_status()

    @_http_retry
    async def _call_pdl_ip_enrich(self, visitor: Visitor) -> str | None:
        """Call PDL /v5/ip/enrich — returns company domain or None.

        Retries up to 3× on transient errors (5xx, 429, timeouts).
        Returns None (no retry) on 400/404 — those are legitimate non-matches.
        """
        if not settings.people_data_labs_api_key:
            return None
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                "https://api.peopledatalabs.com/v5/ip/enrich",
                headers={"X-Api-Key": settings.people_data_labs_api_key},
                params={"ip": visitor.ip_address},
            )
            if resp.status_code == 200:
                body = resp.json()
                company = body.get("company", {}) or {}
                domain = company.get("website") or company.get("display_name")

                # Extract company domain from website URL if full URL
                if domain and domain.startswith("http"):
                    from urllib.parse import urlparse
                    domain = urlparse(domain).netloc or domain

                # Also grab location data from IP
                ip_data = body.get("ip", {}) or {}
                location = ip_data.get("location", {}) or {}
                if location:
                    # Best-effort update of visitor location if empty
                    if not visitor.country_code and location.get("country"):
                        visitor.country_code = location["country"]

                if domain:
                    logger.info(
                        "pdl_ip_enrich_match",
                        ip=visitor.ip_address[:8],
                        company=company.get("display_name", ""),
                        domain=domain,
                    )
                    return domain

            elif resp.status_code == 404:
                logger.debug("pdl_ip_no_match", ip=visitor.ip_address[:8])
            elif resp.status_code == 400:
                logger.debug("pdl_ip_unresolvable", ip=visitor.ip_address[:8],
                             detail="IP is hosting/proxy/VPN — cannot resolve to company")
            else:
                logger.warning("pdl_ip_error", status=resp.status_code, ip=visitor.ip_address[:8])
                self._raise_if_transient(resp)
        return None

    # ──────────────────── Provider: IPinfo ────────────────────

    async def _try_ipinfo_company(self, visitor: Visitor) -> str | None:
        """Resolve IP → company domain via IPinfo. Returns domain or None."""
        start = time.monotonic()

        domain = await self._call_ipinfo_api(visitor)

        elapsed_ms = int((time.monotonic() - start) * 1000)
        cost = 0.0  # IPinfo free tier
        await self._log_resolution(visitor, "ipinfo", domain is not None, cost, elapsed_ms)

        if domain:
            logger.info("ipinfo_company_found", visitor_id=visitor.visitor_id[:8], domain=domain)
        return domain

    # Well-known org name → domain mapping for IPinfo free tier
    # (free tier returns org but not company.domain)
    _ORG_DOMAIN_MAP: dict[str, str] = {
        "microsoft corporation": "microsoft.com",
        "microsoft corp": "microsoft.com",
        "apple inc.": "apple.com",
        "apple inc": "apple.com",
        "google llc": "google.com",
        "google inc": "google.com",
        "amazon.com, inc.": "amazon.com",
        "amazon technologies inc.": "amazon.com",
        "meta platforms, inc.": "meta.com",
        "facebook, inc.": "meta.com",
        "salesforce, inc.": "salesforce.com",
        "salesforce.com, inc.": "salesforce.com",
        "github, inc.": "github.com",
        "oracle corporation": "oracle.com",
        "ibm": "ibm.com",
        "intel corporation": "intel.com",
        "cisco systems, inc.": "cisco.com",
        "adobe inc.": "adobe.com",
        "netflix, inc.": "netflix.com",
        "spotify ab": "spotify.com",
        "twitter, inc.": "x.com",
        "cloudflare, inc.": "cloudflare.com",
        "shopify inc.": "shopify.com",
        "stripe, inc.": "stripe.com",
        "hubspot, inc.": "hubspot.com",
        "zoom video communications, inc.": "zoom.us",
        "slack technologies, llc": "slack.com",
        "atlassian pty ltd": "atlassian.com",
        "datadog, inc.": "datadoghq.com",
        "twilio inc.": "twilio.com",
        "wikimedia foundation inc.": "wikimedia.org",
    }

    # ISP/hosting/telco org names to filter out
    _ISP_KEYWORDS: set[str] = {
        "comcast", "verizon", "at&t", "t-mobile", "sprint", "charter",
        "cox communications", "centurylink", "spectrum", "frontier",
        "vnpt", "viettel", "fpt telecom", "mobifone",
        "bt group", "vodafone", "orange", "deutsche telekom",
        "ovh", "hetzner", "digitalocean", "linode", "vultr",
        "amazon web services", "google cloud", "azure",
    }

    def _org_to_domain(self, org: str) -> str | None:
        """Try to extract a company domain from IPinfo org string.

        IPinfo free tier returns org like 'AS8075 Microsoft Corporation'.
        We strip the ASN prefix and look up in known mappings.
        Falls back to heuristic: if org looks corporate, try {name}.com.
        """
        if not org:
            return None

        # Strip ASN prefix: "AS8075 Microsoft Corporation" → "Microsoft Corporation"
        name = org
        if name.startswith("AS"):
            parts = name.split(" ", 1)
            name = parts[1] if len(parts) > 1 else name
        name_lower = name.strip().lower()

        # Filter ISPs/hosting/telcos
        for isp_kw in self._ISP_KEYWORDS:
            if isp_kw in name_lower:
                logger.debug("ipinfo_filtered_isp", org=org)
                return None

        # Exact match in known map
        if name_lower in self._ORG_DOMAIN_MAP:
            return self._ORG_DOMAIN_MAP[name_lower]

        # Partial match: check if any key is contained in the org name
        for key, domain in self._ORG_DOMAIN_MAP.items():
            if key in name_lower:
                return domain

        # Heuristic: clean org name → try as domain
        # "Acme Corp" → "acmecorp.com"
        # Only for names that look like real companies (2+ words, not too short)
        words = name_lower.replace(",", "").replace(".", "").replace("inc", "").replace("llc", "").replace("ltd", "").replace("corp", "").split()
        words = [w for w in words if len(w) > 1]
        if len(words) >= 1 and len(words) <= 3:
            candidate = "".join(words) + ".com"
            if len(candidate) > 5:  # at least x.com
                logger.info("ipinfo_heuristic_domain", org=org, candidate=candidate)
                return candidate

        return None

    def _is_known_domain(self, domain: str) -> bool:
        """Return True if domain is directly from the _ORG_DOMAIN_MAP (not heuristic)."""
        return domain in set(self._ORG_DOMAIN_MAP.values())

    async def _verify_domain_exists(self, domain: str) -> bool:
        """DNS check: return True if domain resolves, False otherwise."""
        try:
            loop = asyncio.get_event_loop()
            await loop.getaddrinfo(domain, None)
            return True
        except (socket.gaierror, OSError):
            return False

    @_http_retry
    async def _call_ipinfo_api(self, visitor: Visitor) -> str | None:
        """Query IPinfo for company domain from IP.

        Retries up to 3× on transient errors (5xx, 429, timeouts).
        """
        if not settings.ipinfo_token:
            return None
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"https://ipinfo.io/{visitor.ip_address}",
                params={"token": settings.ipinfo_token},
            )
            if resp.status_code == 200:
                data = resp.json()
                org = data.get("org", "")
                company = data.get("company", {})

                # Business+ plan has company.domain directly
                domain = company.get("domain") if isinstance(company, dict) else None

                # Filter out ISPs/hosting if company data available
                comp_type = company.get("type", "") if isinstance(company, dict) else ""
                if comp_type in ("isp", "hosting"):
                    logger.debug("ipinfo_filtered_isp", org=org)
                    return None

                # Free tier fallback: extract domain from org name
                if not domain and org:
                    domain = self._org_to_domain(org)

                # DNS verification for heuristic domains
                if domain and not self._is_known_domain(domain):
                    dns_ok = await self._verify_domain_exists(domain)
                    if not dns_ok:
                        logger.info(
                            "ipinfo_heuristic_domain_dns_fail",
                            domain=domain,
                            org=org,
                        )
                        domain = None

                # Also grab location data
                if not visitor.country_code:
                    country = data.get("country")
                    if country:
                        visitor.country_code = country

                return domain
            else:
                logger.warning("ipinfo_api_error", status=resp.status_code)
                self._raise_if_transient(resp)
        return None

    # ──────────────────── Provider: Hunter.io ────────────────────

    async def _try_hunter_domain(
        self, visitor: Visitor, domain: str
    ) -> IdentifiedVisitor | None:
        """Use Hunter.io to find employee emails from company domain."""
        start = time.monotonic()

        offset = await self._count_identified_for_domain(visitor.site_id, domain)
        data = await self._call_hunter_api(domain, offset=offset)
        success = data is not None

        elapsed_ms = int((time.monotonic() - start) * 1000)
        cost = 0.0  # Hunter free tier
        await self._log_resolution(visitor, "hunter", success, cost, elapsed_ms)

        if data:
            return await self._save_identified(visitor, data, "hunter")
        return None

    @_http_retry
    async def _call_hunter_api(self, domain: str, offset: int = 0) -> dict | None:
        """Hunter domain search — returns contact at position `offset` to avoid dedup.

        Retries up to 3× on transient errors (5xx, 429, timeouts).
        """
        if not settings.hunter_api_key:
            return None
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                "https://api.hunter.io/v2/domain-search",
                params={
                    "domain": domain,
                    "api_key": settings.hunter_api_key,
                    "limit": 5,
                    "offset": offset,
                },
            )
            if resp.status_code == 200:
                body = resp.json().get("data", {})
                emails = body.get("emails", [])
                if emails:
                    # Pick position 0 within this batch (offset handles cycling)
                    person = emails[0]
                    first = person.get("first_name", "")
                    last = person.get("last_name", "")
                    return {
                        "email": person.get("value"),
                        "full_name": f"{first} {last}".strip() or None,
                        "city": None,
                        "region": None,
                        "country": None,
                        "confidence_score": (person.get("confidence", 50) / 100.0),
                    }
            elif resp.status_code == 404:
                logger.debug("hunter_no_match", domain=domain)
            else:
                logger.warning("hunter_api_error", status=resp.status_code)
                self._raise_if_transient(resp)
        return None

    # ──────────────────── Provider: Apollo.io ────────────────────

    async def _try_apollo(
        self, visitor: Visitor, company_domain: str
    ) -> IdentifiedVisitor | None:
        """Use Apollo.io to find contacts at a company domain."""
        start = time.monotonic()

        offset = await self._count_identified_for_domain(visitor.site_id, company_domain)
        data = await self._call_apollo_api(company_domain, offset=offset)
        success = data is not None

        elapsed_ms = int((time.monotonic() - start) * 1000)
        cost = 0.0  # Apollo free tier
        await self._log_resolution(visitor, "apollo", success, cost, elapsed_ms)

        if data:
            return await self._save_identified(visitor, data, "apollo")
        return None

    @_http_retry
    async def _call_apollo_api(self, company_domain: str, offset: int = 0) -> dict | None:
        """Apollo people search by company domain — uses page cycling to avoid dedup.

        Retries up to 3× on transient errors (5xx, 429, timeouts).
        """
        if not settings.apollo_api_key:
            return None
        # Apollo uses 1-based page numbers; offset 0→page 1, offset 1→page 2, etc.
        page = offset + 1
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                "https://api.apollo.io/v1/mixed_people/search",
                headers={"X-Api-Key": settings.apollo_api_key},
                json={
                    "q_organization_domains": company_domain,
                    "per_page": 1,
                    "page": page,
                },
            )
            if resp.status_code == 200:
                people = resp.json().get("people", [])
                if people:
                    p = people[0]
                    return {
                        "email": p.get("email"),
                        "full_name": p.get("name"),
                        "city": p.get("city"),
                        "region": p.get("state"),
                        "country": p.get("country"),
                        "confidence_score": 0.6,
                    }
            elif resp.status_code == 404:
                logger.debug("apollo_no_match", domain=company_domain)
            else:
                logger.warning("apollo_api_error", status=resp.status_code)
                self._raise_if_transient(resp)
        return None

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

