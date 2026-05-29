"""Clay-style waterfall identity resolution.

Multiple providers tried in order:

1. PDL IP Enrich (IP → company domain + location)   ~30-40% match
2. IPinfo (IP → company domain) — fallback           ~20-30% match
3. Hunter (domain → employee emails)                 ~50% from domain
4. Apollo (domain → contact lookup)                  ~40% fallback

PDL and IPinfo both resolve IP → company. First to return a domain
feeds Hunter for email lookup, then Apollo as final fallback.
"""

import asyncio
import random
import socket
import time
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import structlog
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.config import settings
from apps.api.models.visitor import IdentifiedVisitor, ResolutionLog, Visitor

logger = structlog.get_logger()

REDIS_RESOLUTION_PREFIX = "resolution:"
RESOLUTION_CACHE_TTL = 30 * 86400  # 30 days


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

    async def check_daily_budget(self, site_id: str) -> bool:
        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        result = await self.db.execute(
            select(func.count()).select_from(ResolutionLog).where(
                ResolutionLog.site_id == site_id,
                ResolutionLog.created_at >= today_start,
            )
        )
        count = result.scalar() or 0
        return count < settings.default_daily_resolution_budget

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

    # ──────────────────── Main Waterfall ────────────────────

    async def resolve(self, visitor: Visitor) -> IdentifiedVisitor | None:
        """Waterfall identity resolution — try providers in order.

        Flow:
        0. RB2B Identity Graph (IP → hashed email → person) — PERSON-LEVEL
        1. PDL IP Enrich (IP → company domain + location)
        2. IPinfo (IP → company domain) — fallback if PDL missed
        3. Hunter (domain → employee emails)    ← company-level fallback
        4. Apollo (domain → contact)            ← company-level fallback
        """
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

        # ══════════════════════════════════════════════════════════════
        # Step 0: Identity Graph — PERSON-LEVEL identification
        # Leadpipe / RB2B resolve visitors via cookie/device graph.
        # Works even for residential IPs if person is in the graph.
        # ══════════════════════════════════════════════════════════════

        # 0a. Leadpipe (pixel-based identity graph — 500 free IDs)
        result = await self._try_leadpipe_identify(visitor)
        if result:
            return result

        # 0b. Capturify (pixel-based, claims 60% match rate)
        result = await self._try_capturify_identify(visitor)
        if result:
            return result

        # 0c. RB2B (server-side IP → person, US only)
        result = await self._try_rb2b_identify(visitor)
        if result:
            return result

        # ══════════════════════════════════════════════════════════════
        # Steps 1-4: IP → Company → Employee FALLBACK
        # Only reaches here if identity graph had no match.
        # This identifies the COMPANY, then picks an employee — lower
        # confidence than identity graph (company-level, not person).
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
            # ── Step 1: PDL IP Enrich (IP → company domain) ──
            company_domain = await self._try_pdl_ip_enrich(visitor)

            # ── Step 2: IPinfo (IP → company domain) — fallback ──
            if not company_domain:
                company_domain = await self._try_ipinfo_company(visitor)

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

        if settings.mock_external_apis:
            data = self._mock_leadpipe_response(visitor)
            success = data is not None
        else:
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

    async def _call_leadpipe_api(self, visitor: Visitor) -> dict | None:
        """Query Leadpipe for identified visitors matching this visitor's session.

        Match logic: Look for Leadpipe identifications from the same IP
        within a short time window of the visitor's last_seen timestamp.
        """
        async with httpx.AsyncClient(timeout=15.0) as client:
            try:
                # Query recent identifications, filter by page URL or IP
                resp = await client.get(
                    f"{self.LEADPIPE_API_BASE}/v1/data",
                    headers={"X-API-Key": settings.leadpipe_api_key},
                    params={
                        "limit": 10,
                        "sort": "desc",
                    },
                )

                if resp.status_code != 200:
                    logger.warning("leadpipe_api_error", status=resp.status_code,
                                   detail=resp.text[:200])
                    return None

                body = resp.json()
                visitors_data = body.get("data", [])

                if not visitors_data:
                    logger.debug("leadpipe_no_matches")
                    return None

                # Find a match by IP address or page URL containing site domain
                site_domain = None
                if hasattr(visitor, "site_id"):
                    # Try to extract site domain from visitor's pages
                    pages = getattr(visitor, "pages_visited", []) or []
                    if pages:
                        from urllib.parse import urlparse
                        try:
                            site_domain = urlparse(pages[0]).netloc
                        except Exception:
                            pass

                for lp_visitor in visitors_data:
                    lp_email = lp_visitor.get("email") or lp_visitor.get("emails", [None])[0] if isinstance(lp_visitor.get("emails"), list) and lp_visitor.get("emails") else lp_visitor.get("email")
                    if not lp_email:
                        continue

                    # Match by IP if available
                    lp_ip = lp_visitor.get("ip") or lp_visitor.get("ipAddress")
                    if lp_ip and lp_ip == visitor.ip_address:
                        return self._parse_leadpipe_person(lp_visitor)

                    # Match by page URL containing our site domain
                    lp_pages = lp_visitor.get("pagesViewed") or lp_visitor.get("pages") or []
                    if site_domain and any(site_domain in str(p) for p in lp_pages):
                        return self._parse_leadpipe_person(lp_visitor)

                logger.debug("leadpipe_no_ip_match", ip=visitor.ip_address[:8])
                return None

            except httpx.HTTPError as e:
                logger.error("leadpipe_api_error", error=str(e))
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

    def _mock_leadpipe_response(self, visitor: Visitor) -> dict | None:
        """Mock: ~35% chance of identity graph match."""
        if random.random() > 0.35:
            return None
        first_names = ["Emma", "James", "Olivia", "Noah", "Sophia"]
        last_names = ["Martinez", "Anderson", "Thomas", "Jackson", "White"]
        domains = ["innovate.io", "startuplab.com", "saasworks.co"]
        fn = random.choice(first_names)
        ln = random.choice(last_names)
        domain = random.choice(domains)
        return {
            "email": f"{fn.lower()}.{ln.lower()}@{domain}",
            "full_name": f"{fn} {ln}",
            "city": random.choice(["San Francisco", "London", "Berlin", "Singapore"]),
            "region": random.choice(["CA", "England", "Berlin", "SG"]),
            "country": random.choice(["US", "GB", "DE", "SG"]),
            "confidence_score": 0.95,
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

        if settings.mock_external_apis:
            data = self._mock_capturify_response(visitor)
            success = data is not None
        else:
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

    async def _call_capturify_api(self, visitor: Visitor) -> dict | None:
        """Query Capturify for identified visitors matching this visitor.

        Uses the same pattern as Leadpipe: query recent identifications,
        match by IP address, parse person data.
        """
        async with httpx.AsyncClient(timeout=15.0) as client:
            try:
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

                for cap_visitor in visitors_data:
                    # Match by IP address
                    cap_ip = (
                        cap_visitor.get("ip")
                        or cap_visitor.get("ipAddress")
                        or cap_visitor.get("ip_address")
                    )
                    if cap_ip and cap_ip == visitor.ip_address:
                        return self._parse_capturify_person(cap_visitor)

                logger.debug("capturify_no_ip_match", ip=visitor.ip_address[:8])
                return None

            except httpx.HTTPError as e:
                logger.error("capturify_api_error", error=str(e))
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

    def _mock_capturify_response(self, visitor: Visitor) -> dict | None:
        """Mock: ~40% chance of identity graph match."""
        if random.random() > 0.40:
            return None
        first_names = ["Chris", "Dana", "Morgan", "Alex", "Jordan"]
        last_names = ["Taylor", "Rivera", "Mitchell", "Carter", "Brooks"]
        domains = ["buildfast.io", "scaleup.com", "founderhq.co"]
        fn = random.choice(first_names)
        ln = random.choice(last_names)
        domain = random.choice(domains)
        return {
            "email": f"{fn.lower()}.{ln.lower()}@{domain}",
            "full_name": f"{fn} {ln}",
            "city": random.choice(["Austin", "Denver", "Miami", "Chicago"]),
            "region": random.choice(["TX", "CO", "FL", "IL"]),
            "country": "US",
            "confidence_score": 0.90,
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

        if settings.mock_external_apis:
            data = self._mock_rb2b_response(visitor)
            success = data is not None
        else:
            data = await self._call_rb2b_api(visitor)
            success = data is not None

        elapsed_ms = int((time.monotonic() - start) * 1000)
        cost = 0.09 if (not settings.mock_external_apis and success) else 0.0
        await self._log_resolution(visitor, "rb2b_identity_graph", success, cost, elapsed_ms)

        if data:
            logger.info(
                "rb2b_person_identified",
                visitor_id=visitor.visitor_id[:8],
                email=data.get("email", "")[:5] + "***" if data.get("email") else None,
            )
            return await self._save_identified(visitor, data, "rb2b")
        return None

    async def _call_rb2b_api(self, visitor: Visitor) -> dict | None:
        """Call RB2B API Suite: IP to HEM → HEM to Business Profile.

        Two-step chain:
        1. IP → Hashed Email (HEM)
        2. HEM → Full business profile (name, email, LinkedIn, job title)
        """
        async with httpx.AsyncClient(timeout=15.0) as client:
            try:
                # Step 1: IP → Hashed Email Match (HEM)
                resp = await client.post(
                    "https://api.rb2b.com/v2/ip-to-hem",
                    headers={
                        "Authorization": f"Bearer {settings.rb2b_api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "ip": visitor.ip_address,
                        "userAgent": getattr(visitor, "user_agent", "") or "",
                    },
                )

                if resp.status_code != 200:
                    if resp.status_code == 404:
                        logger.debug("rb2b_no_match", ip=visitor.ip_address[:8])
                    else:
                        logger.warning("rb2b_ip_error", status=resp.status_code,
                                       detail=resp.text[:200])
                    return None

                hem_data = resp.json()
                hem = hem_data.get("hem") or hem_data.get("hashedEmail") or hem_data.get("data", {}).get("hem")
                if not hem:
                    logger.debug("rb2b_no_hem", ip=visitor.ip_address[:8])
                    return None

                # Step 2: HEM → Business Profile
                profile_resp = await client.post(
                    "https://api.rb2b.com/v2/hem-to-business-profile",
                    headers={
                        "Authorization": f"Bearer {settings.rb2b_api_key}",
                        "Content-Type": "application/json",
                    },
                    json={"hem": hem},
                )

                if profile_resp.status_code != 200:
                    # Got HEM but can't enrich — still try to use it
                    logger.warning("rb2b_profile_error", status=profile_resp.status_code)
                    return None

                profile = profile_resp.json()
                person = profile.get("data", profile)

                email = person.get("email") or person.get("workEmail") or person.get("personalEmail")
                if not email:
                    logger.debug("rb2b_no_email_in_profile", ip=visitor.ip_address[:8])
                    return None

                return {
                    "email": email,
                    "full_name": person.get("fullName") or person.get("name"),
                    "city": person.get("city"),
                    "region": person.get("state") or person.get("region"),
                    "country": person.get("country", "US"),
                    "confidence_score": 0.95,  # Identity graph = high confidence
                }

            except httpx.HTTPError as e:
                logger.error("rb2b_api_error", error=str(e))
        return None

    def _mock_rb2b_response(self, visitor: Visitor) -> dict | None:
        """Mock: ~30% chance of identity graph match (simulates US B2B traffic)."""
        if random.random() > 0.30:
            return None
        first_names = ["Sarah", "Mike", "Emily", "David", "Lisa"]
        last_names = ["Johnson", "Williams", "Brown", "Davis", "Wilson"]
        domains = ["techcorp.com", "growthstartup.io", "saascompany.com"]
        fn = random.choice(first_names)
        ln = random.choice(last_names)
        domain = random.choice(domains)
        return {
            "email": f"{fn.lower()}.{ln.lower()}@{domain}",
            "full_name": f"{fn} {ln}",
            "city": random.choice(["San Francisco", "New York", "Austin", "Seattle"]),
            "region": random.choice(["CA", "NY", "TX", "WA"]),
            "country": "US",
            "confidence_score": 0.95,
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

        if settings.mock_external_apis:
            domain = self._mock_pdl_response(visitor)
            success = domain is not None
        else:
            domain = await self._call_pdl_ip_enrich(visitor)
            success = domain is not None

        elapsed_ms = int((time.monotonic() - start) * 1000)
        cost = 0.01 if (not settings.mock_external_apis and success) else 0.0
        await self._log_resolution(visitor, "pdl_ip_enrich", success, cost, elapsed_ms)

        if domain:
            logger.info("pdl_ip_company_found", visitor_id=visitor.visitor_id[:8], domain=domain)
        return domain

    async def _call_pdl_ip_enrich(self, visitor: Visitor) -> str | None:
        """Call PDL /v5/ip/enrich — returns company domain or None."""
        if not settings.people_data_labs_api_key:
            return None
        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
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
            except httpx.HTTPError as e:
                logger.error("pdl_ip_api_error", error=str(e))
        return None

    # ──────────────────── Provider: IPinfo ────────────────────

    async def _try_ipinfo_company(self, visitor: Visitor) -> str | None:
        """Resolve IP → company domain via IPinfo. Returns domain or None."""
        start = time.monotonic()

        if settings.mock_external_apis:
            domain = self._mock_ipinfo_response(visitor)
        else:
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

    async def _call_ipinfo_api(self, visitor: Visitor) -> str | None:
        if not settings.ipinfo_token:
            return None
        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
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
            except httpx.HTTPError as e:
                logger.error("ipinfo_api_error", error=str(e))
        return None

    # ──────────────────── Provider: Hunter.io ────────────────────

    async def _try_hunter_domain(
        self, visitor: Visitor, domain: str
    ) -> IdentifiedVisitor | None:
        """Use Hunter.io to find employee emails from company domain."""
        start = time.monotonic()

        if settings.mock_external_apis:
            data = self._mock_hunter_response(visitor, domain)
            success = data is not None
        else:
            offset = await self._count_identified_for_domain(visitor.site_id, domain)
            data = await self._call_hunter_api(domain, offset=offset)
            success = data is not None

        elapsed_ms = int((time.monotonic() - start) * 1000)
        cost = 0.0  # Hunter free tier
        await self._log_resolution(visitor, "hunter", success, cost, elapsed_ms)

        if data:
            return await self._save_identified(visitor, data, "hunter")
        return None

    async def _call_hunter_api(self, domain: str, offset: int = 0) -> dict | None:
        """Hunter domain search — returns contact at position `offset` to avoid dedup."""
        if not settings.hunter_api_key:
            return None
        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
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
            except httpx.HTTPError as e:
                logger.error("hunter_api_error", error=str(e))
        return None

    # ──────────────────── Provider: Apollo.io ────────────────────

    async def _try_apollo(
        self, visitor: Visitor, company_domain: str
    ) -> IdentifiedVisitor | None:
        """Use Apollo.io to find contacts at a company domain."""
        start = time.monotonic()

        if settings.mock_external_apis:
            data = self._mock_apollo_response(visitor, company_domain)
            success = data is not None
        else:
            offset = await self._count_identified_for_domain(visitor.site_id, company_domain)
            data = await self._call_apollo_api(company_domain, offset=offset)
            success = data is not None

        elapsed_ms = int((time.monotonic() - start) * 1000)
        cost = 0.0  # Apollo free tier
        await self._log_resolution(visitor, "apollo", success, cost, elapsed_ms)

        if data:
            return await self._save_identified(visitor, data, "apollo")
        return None

    async def _call_apollo_api(self, company_domain: str, offset: int = 0) -> dict | None:
        """Apollo people search by company domain — uses page cycling to avoid dedup."""
        if not settings.apollo_api_key:
            return None
        # Apollo uses 1-based page numbers; offset 0→page 1, offset 1→page 2, etc.
        page = offset + 1
        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
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
            except httpx.HTTPError as e:
                logger.error("apollo_api_error", error=str(e))
        return None

    # ──────────────────── Save + Log ────────────────────

    async def _save_identified(
        self, visitor: Visitor, data: dict, provider: str
    ) -> IdentifiedVisitor:
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
        await self.db.commit()
        logger.info(
            "visitor_identified",
            visitor_id=visitor.visitor_id[:8],
            provider=provider,
            email=data.get("email", "")[:5] + "***" if data.get("email") else None,
        )
        return identified

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
        await self.db.commit()

    # ──────────────────── Mock data ────────────────────

    def _mock_pdl_response(self, visitor: Visitor) -> str | None:
        """Mock: ~60% chance of returning a company domain from IP."""
        if random.random() > 0.60:
            return None
        return random.choice([
            "acmecorp.com", "techstartup.io", "growthbase.com",
            "saasplatform.co", "digitalagency.com", "datascience.io",
        ])

    def _mock_ipinfo_response(self, visitor: Visitor) -> str | None:
        """Mock: ~70% chance of returning a company domain."""
        if random.random() > 0.70:
            return None
        return random.choice([
            "techstartup.com", "scaleai.co", "cloudventure.io",
            "datadrivenlabs.com", "indiesaas.io",
        ])

    def _mock_hunter_response(self, visitor: Visitor, domain: str) -> dict | None:
        """Mock: ~50% chance of finding an email from domain."""
        if random.random() > 0.50:
            return None
        first_names = ["Alex", "Jordan", "Taylor", "Morgan", "Casey"]
        last_names = ["Reed", "Park", "Chen", "Nguyen", "Patel"]
        fn = random.choice(first_names)
        ln = random.choice(last_names)
        return {
            "email": f"{fn.lower()}.{ln.lower()}@{domain}",
            "full_name": f"{fn} {ln}",
            "city": None,
            "region": None,
            "country": None,
            "confidence_score": round(random.uniform(0.6, 0.9), 2),
        }

    def _mock_apollo_response(self, visitor: Visitor, domain: str) -> dict | None:
        """Mock: ~40% chance of finding a contact."""
        if random.random() > 0.40:
            return None
        first_names = ["Sam", "Riley", "Jamie", "Quinn", "Drew"]
        last_names = ["Kim", "Lopez", "Singh", "O'Brien", "Costa"]
        fn = random.choice(first_names)
        ln = random.choice(last_names)
        return {
            "email": f"{fn.lower()}@{domain}",
            "full_name": f"{fn} {ln}",
            "city": random.choice(["London", "Berlin", "Tokyo", "Sydney"]),
            "region": None,
            "country": random.choice(["GB", "DE", "JP", "AU"]),
            "confidence_score": 0.6,
        }
