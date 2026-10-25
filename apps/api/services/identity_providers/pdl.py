"""People Data Labs provider mixin: person enrich (from email) + IP enrich."""

import time

import httpx
import structlog

from apps.api.config import settings
from apps.api.models.visitor import IdentifiedVisitor, Visitor
from apps.api.services.identity_providers.base import (
    ProviderUnavailableError,
    _http_retry,
)

logger = structlog.get_logger()


class PDLMixin:
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
                # 200/400/404 already handled above as real answers; anything
                # left here (401 bad key, 402 quota) is the account failing.
                raise ProviderUnavailableError(
                    "pdl_ip_enrich", f"HTTP {resp.status_code}"
                )
        return None


async def enrich_company_by_domain(domain: str) -> dict | None:
    """PDL ``/v5/company/enrich`` by website domain — read-only firmographics.

    Used by the paid ``/api/v1/paid/company-from-domain`` route. Returns a curated
    dict on a match, ``None`` on a legitimate non-match (404). Raises
    ``ProviderUnavailableError`` when PDL is not configured or the account fails
    (401/402/429/5xx/transport) so the paid caller does NOT settle the payment.
    Company-level data only — no person fields are requested or returned.
    """
    if settings.mock_external_apis:
        return {
            "domain": domain,
            "name": f"Mock Company ({domain})",
            "industry": "computer software",
            "size": "11-50",
            "employee_count": 25,
            "founded": 2020,
            "country": "united states",
            "locality": "san francisco",
            "linkedin_url": None,
            "twitter_url": None,
        }
    if not settings.people_data_labs_api_key:
        raise ProviderUnavailableError("pdl_company_enrich", "not configured")
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                "https://api.peopledatalabs.com/v5/company/enrich",
                headers={"X-Api-Key": settings.people_data_labs_api_key},
                params={"website": domain, "pretty": "false"},
            )
    except httpx.HTTPError as exc:
        logger.warning("pdl_company_enrich_exception", error=type(exc).__name__)
        raise ProviderUnavailableError("pdl_company_enrich", type(exc).__name__) from exc

    if resp.status_code == 404:
        logger.debug("pdl_company_enrich_no_match", domain=domain)
        return None
    if resp.status_code != 200:
        logger.warning("pdl_company_enrich_error", status=resp.status_code)
        raise ProviderUnavailableError("pdl_company_enrich", f"HTTP {resp.status_code}")

    body = resp.json() or {}
    location = body.get("location") or {}
    return {
        "domain": domain,
        "name": body.get("display_name") or body.get("name"),
        "industry": body.get("industry"),
        "size": body.get("size"),
        "employee_count": body.get("employee_count"),
        "founded": body.get("founded"),
        "country": location.get("country"),
        "locality": location.get("locality"),
        "linkedin_url": body.get("linkedin_url"),
        "twitter_url": body.get("twitter_url"),
    }
