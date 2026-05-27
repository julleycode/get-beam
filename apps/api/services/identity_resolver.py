"""Clay-style waterfall identity resolution.

Multiple providers tried in order — first match wins:

1. PDL identify (IP → person)                       ~10-15% match
2. IPinfo (IP → company domain) + Hunter (domain → emails)  ~20-30% match
3. Apollo (company + signals → contact lookup)       ~10-20% match

Each provider's output cascades into the next — e.g. IPinfo returns
company domain, which feeds Hunter's domain→email search.
"""

import random
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

    # ──────────────────── Main Waterfall ────────────────────

    async def resolve(self, visitor: Visitor) -> IdentifiedVisitor | None:
        """Waterfall identity resolution — try providers in order.

        Flow:
        1. PDL (IP → person) — direct match, best quality
        2. IPinfo (IP → company) + Hunter (domain → emails) — indirect path
        3. Apollo (company → contact) — database lookup fallback
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

        # ── Step 1: PDL (IP → person) — direct, best quality ──
        result = await self._try_people_data_labs(visitor)
        if result:
            return result

        # ── Step 2: IPinfo (IP → company) + Hunter (domain → emails) ──
        company_domain = await self._try_ipinfo_company(visitor)
        if company_domain:
            # Store company domain on visitor for future use
            visitor.company_domain = company_domain
            await self.db.commit()

            result = await self._try_hunter_domain(visitor, company_domain)
            if result:
                return result

        # ── Step 3: Apollo (company → contact lookup) ──
        if company_domain:
            result = await self._try_apollo(visitor, company_domain)
            if result:
                return result

        # No match from any provider
        visitor.identity_status = "unresolvable"
        await self.db.commit()
        return None

    # ──────────────────── Provider: PDL ────────────────────

    async def _try_people_data_labs(self, visitor: Visitor) -> IdentifiedVisitor | None:
        start = time.monotonic()

        if settings.mock_external_apis:
            data = self._mock_pdl_response(visitor)
            success = data is not None
        else:
            data = await self._call_pdl_api(visitor)
            success = data is not None

        elapsed_ms = int((time.monotonic() - start) * 1000)
        cost = 0.03 if not settings.mock_external_apis else 0.0
        await self._log_resolution(visitor, "people_data_labs", success, cost, elapsed_ms)

        if data:
            return await self._save_identified(visitor, data, "people_data_labs")
        return None

    async def _call_pdl_api(self, visitor: Visitor) -> dict | None:
        if not settings.people_data_labs_api_key:
            return None
        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                resp = await client.get(
                    "https://api.peopledatalabs.com/v5/person/identify",
                    headers={"X-Api-Key": settings.people_data_labs_api_key},
                    params={"ip": visitor.ip_address},
                )
                if resp.status_code == 200:
                    body = resp.json()
                    if body.get("data"):
                        person = body["data"][0] if isinstance(body["data"], list) else body["data"]
                        emails = person.get("personal_emails") or []
                        return {
                            "email": person.get("work_email") or (emails[0] if emails else None),
                            "full_name": person.get("full_name"),
                            "city": person.get("location_locality"),
                            "region": person.get("location_region"),
                            "country": person.get("location_country"),
                            "confidence_score": body.get("likelihood", 0.5),
                        }
                logger.debug("pdl_no_match", status=resp.status_code, ip=visitor.ip_address[:8])
            except httpx.HTTPError as e:
                logger.error("pdl_api_error", error=str(e))
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
                    domain = company.get("domain") if isinstance(company, dict) else None

                    # Filter out ISPs/hosting — only return real companies
                    comp_type = company.get("type", "") if isinstance(company, dict) else ""
                    if comp_type in ("isp", "hosting"):
                        logger.debug("ipinfo_filtered_isp", org=org)
                        return None

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
            data = await self._call_hunter_api(domain)
            success = data is not None

        elapsed_ms = int((time.monotonic() - start) * 1000)
        cost = 0.0  # Hunter free tier
        await self._log_resolution(visitor, "hunter", success, cost, elapsed_ms)

        if data:
            return await self._save_identified(visitor, data, "hunter")
        return None

    async def _call_hunter_api(self, domain: str) -> dict | None:
        """Hunter domain search → first employee with highest confidence."""
        if not settings.hunter_api_key:
            return None
        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                resp = await client.get(
                    "https://api.hunter.io/v2/domain-search",
                    params={
                        "domain": domain,
                        "api_key": settings.hunter_api_key,
                        "limit": 1,
                    },
                )
                if resp.status_code == 200:
                    body = resp.json().get("data", {})
                    emails = body.get("emails", [])
                    if emails:
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
            data = await self._call_apollo_api(company_domain)
            success = data is not None

        elapsed_ms = int((time.monotonic() - start) * 1000)
        cost = 0.0  # Apollo free tier
        await self._log_resolution(visitor, "apollo", success, cost, elapsed_ms)

        if data:
            return await self._save_identified(visitor, data, "apollo")
        return None

    async def _call_apollo_api(self, company_domain: str) -> dict | None:
        """Apollo people search by company domain → first contact."""
        if not settings.apollo_api_key:
            return None
        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                resp = await client.post(
                    "https://api.apollo.io/v1/mixed_people/search",
                    headers={"X-Api-Key": settings.apollo_api_key},
                    json={
                        "q_organization_domains": company_domain,
                        "per_page": 1,
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

    def _mock_pdl_response(self, visitor: Visitor) -> dict | None:
        if random.random() > 0.60:
            return None
        first_names = ["John", "Sarah", "Mike", "Emma", "Alex", "Lisa", "David", "Rachel"]
        last_names = ["Smith", "Johnson", "Williams", "Brown", "Jones", "Davis", "Miller", "Wilson"]
        fn = random.choice(first_names)
        ln = random.choice(last_names)
        return {
            "email": f"{fn.lower()}.{ln.lower()}@example.com",
            "full_name": f"{fn} {ln}",
            "city": random.choice(["San Francisco", "New York", "Austin", "Seattle", "Denver"]),
            "region": random.choice(["CA", "NY", "TX", "WA", "CO"]),
            "country": "US",
            "confidence_score": round(random.uniform(0.5, 0.95), 2),
        }

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
