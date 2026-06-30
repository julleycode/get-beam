"""Apollo.io provider mixin: company domain → contact."""

import time

import httpx
import structlog

from apps.api.config import settings
from apps.api.models.visitor import IdentifiedVisitor, Visitor
from apps.api.services.identity_providers.base import _http_retry

logger = structlog.get_logger()


class ApolloMixin:
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
        if not settings.apollo_api_key or not settings.apollo_enabled:
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
