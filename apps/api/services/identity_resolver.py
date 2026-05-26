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

    async def resolve(self, visitor: Visitor) -> IdentifiedVisitor | None:
        if await self.was_recently_attempted(visitor.site_id, visitor.visitor_id):
            logger.info("resolution_skipped_recent_attempt", visitor_id=visitor.visitor_id[:8])
            return None

        if not await self.check_daily_budget(visitor.site_id):
            logger.warning("resolution_budget_exhausted", site_id=visitor.site_id)
            return None

        # Step 1: People Data Labs
        result = await self._try_people_data_labs(visitor)
        if result:
            return result

        # Step 2: FullContact fallback
        result = await self._try_fullcontact(visitor)
        if result:
            return result

        # Mark as unresolvable
        visitor.identity_status = "unresolvable"
        await self.db.commit()
        return None

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

    async def _try_fullcontact(self, visitor: Visitor) -> IdentifiedVisitor | None:
        start = time.monotonic()

        if settings.mock_external_apis:
            data = self._mock_fullcontact_response(visitor)
            success = data is not None
        else:
            data = await self._call_fullcontact_api(visitor)
            success = data is not None

        elapsed_ms = int((time.monotonic() - start) * 1000)
        cost = 0.02 if not settings.mock_external_apis else 0.0

        await self._log_resolution(visitor, "fullcontact", success, cost, elapsed_ms)

        if data:
            return await self._save_identified(visitor, data, "fullcontact")
        return None

    async def _call_pdl_api(self, visitor: Visitor) -> dict | None:
        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                resp = await client.get(
                    "https://api.peopledatalabs.com/v5/person/identify",
                    headers={"X-Api-Key": settings.people_data_labs_api_key},
                    params={"ip": visitor.visitor_id},
                )
                if resp.status_code == 200:
                    body = resp.json()
                    if body.get("data"):
                        person = body["data"][0] if isinstance(body["data"], list) else body["data"]
                        return {
                            "email": person.get("work_email") or person.get("personal_emails", [None])[0],
                            "full_name": person.get("full_name"),
                            "city": person.get("location_locality"),
                            "region": person.get("location_region"),
                            "country": person.get("location_country"),
                            "confidence_score": body.get("likelihood", 0.5),
                        }
            except httpx.HTTPError as e:
                logger.error("pdl_api_error", error=str(e))
        return None

    async def _call_fullcontact_api(self, visitor: Visitor) -> dict | None:
        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                resp = await client.post(
                    "https://api.fullcontact.com/v3/person.enrich",
                    headers={"Authorization": f"Bearer {settings.fullcontact_api_key}"},
                    json={"ip": visitor.visitor_id},
                )
                if resp.status_code == 200:
                    body = resp.json()
                    return {
                        "email": body.get("email"),
                        "full_name": body.get("fullName"),
                        "city": body.get("location", {}).get("city"),
                        "region": body.get("location", {}).get("region"),
                        "country": body.get("location", {}).get("country"),
                        "confidence_score": body.get("likelihood", 0.4),
                    }
            except httpx.HTTPError as e:
                logger.error("fullcontact_api_error", error=str(e))
        return None

    def _mock_pdl_response(self, visitor: Visitor) -> dict | None:
        # ~60% match rate in mock mode for better testing
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

    def _mock_fullcontact_response(self, visitor: Visitor) -> dict | None:
        if random.random() > 0.08:
            return None
        first_names = ["Tom", "Anna", "Chris", "Megan", "James", "Olivia"]
        last_names = ["Taylor", "Anderson", "Thomas", "Jackson", "White", "Harris"]
        fn = random.choice(first_names)
        ln = random.choice(last_names)
        return {
            "email": f"{fn.lower()}.{ln.lower()}@example.com",
            "full_name": f"{fn} {ln}",
            "city": random.choice(["Chicago", "Boston", "Portland", "Miami"]),
            "region": random.choice(["IL", "MA", "OR", "FL"]),
            "country": "US",
            "confidence_score": round(random.uniform(0.4, 0.8), 2),
        }

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
        logger.info("visitor_identified", visitor_id=visitor.visitor_id[:8], provider=provider)
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
