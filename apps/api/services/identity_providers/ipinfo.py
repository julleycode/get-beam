"""IPinfo provider mixin: IP → company domain (with org-name heuristics)."""

import asyncio
import socket

import httpx
import structlog

from apps.api.config import settings
from apps.api.models.visitor import Visitor
from apps.api.services.identity_providers.base import _http_retry

logger = structlog.get_logger()


class IPinfoMixin:
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
