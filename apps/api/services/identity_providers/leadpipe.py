"""Leadpipe identity-graph provider mixin."""

import httpx
import structlog

from apps.api.config import settings
from apps.api.models.visitor import Visitor
from apps.api.services.identity_providers.base import _http_retry

logger = structlog.get_logger()


class LeadpipeMixin:
    LEADPIPE_API_BASE = "https://api.aws53.cloud"

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
