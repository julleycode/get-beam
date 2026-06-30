"""Hunter.io provider mixin: company domain → employee email."""

import time

import httpx
import structlog

from apps.api.config import settings
from apps.api.models.visitor import IdentifiedVisitor, Visitor
from apps.api.services.identity_providers.base import _http_retry

logger = structlog.get_logger()


class HunterMixin:
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
        if not settings.hunter_api_key or not settings.hunter_enabled:
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
