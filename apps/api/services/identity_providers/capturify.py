"""Capturify identity-graph provider mixin.

DISABLED BY DEFAULT (`capturify_enabled=False`). `CAPTURIFY_API_BASE` below was
never confirmed against an official document, and as of 05-08-26 the host
`api.capturify.io` returns NXDOMAIN — it has no DNS record at all. Capturify has
therefore never produced a `resolution_logs` row. The parsing code stays because
`app.capturify.io` (the pixel host referenced in `tracker.js`) does resolve, so the
product is real and only this base URL is wrong. Re-enabling requires a verified
base URL from vendor docs, not a guess.
"""

import httpx
import structlog

from apps.api.config import settings
from apps.api.models.visitor import Visitor
from apps.api.services.identity_providers.base import (
    ProviderUnavailableError,
    _http_retry,
)

logger = structlog.get_logger()


class CapturifyMixin:
    CAPTURIFY_API_BASE = "https://api.capturify.io"

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
                raise ProviderUnavailableError("capturify", "HTTP 401 unauthorized")
            if resp.status_code == 404:
                logger.debug("capturify_no_matches")
                return None
            if resp.status_code != 200:
                logger.warning("capturify_api_error", status=resp.status_code,
                               detail=resp.text[:200])
                self._raise_if_transient(resp)
                if resp.status_code != 400:
                    raise ProviderUnavailableError(
                        "capturify", f"HTTP {resp.status_code}"
                    )
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
