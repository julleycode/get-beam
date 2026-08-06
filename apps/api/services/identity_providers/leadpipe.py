"""Leadpipe identity-graph provider mixin."""

import json

import httpx
import structlog

from apps.api.config import settings
from apps.api.models.visitor import Visitor
from apps.api.services.identity_providers.base import (
    ProviderNotConfiguredError,
    ProviderUnavailableError,
    _http_retry,
)
from apps.api.services.identity_providers.matching import (
    REJECTION_IP_MISMATCH,
    REJECTION_NO_EMAIL,
    log_rejection_tally,
    new_rejection_tally,
)

logger = structlog.get_logger()


class LeadpipeMixin:
    LEADPIPE_API_BASE = "https://api.aws53.cloud"

    # Registered-pixel list, cached per resolver instance and (when available) in
    # Redis. One list call covers every site in a sweep instead of one per visitor.
    LEADPIPE_PIXEL_CACHE_KEY = "leadpipe:active_pixel_domains"
    LEADPIPE_PIXEL_CACHE_TTL = 3600  # 1h — pixels are provisioned, not churned

    async def _leadpipe_active_domains(self) -> set[str]:
        """Domains that have an ACTIVE Leadpipe pixel in this organization.

        Needed because `/v1/data` is blind to the difference that matters:
        a domain with no pixel and a domain with a pixel but no visitors both
        answer `200 {"data": [], "meta": {"total": 0}}` (verified against a live
        org 06-08-26). Only `/v1/data/pixels` can separate them.

        `status` is checked, not just presence — a paused pixel serves no data,
        so gating on existence alone reproduces the same silent-empty symptom.
        """
        cached = getattr(self, "_leadpipe_pixel_domains", None)
        if cached is not None:
            return cached

        # `redis` belongs to IdentityResolver, not to this mixin — read it
        # defensively so the mixin stays usable standalone.
        redis = getattr(self, "redis", None)
        if redis:
            try:
                raw = await redis.get(self.LEADPIPE_PIXEL_CACHE_KEY)
                if raw:
                    domains = set(json.loads(raw))
                    self._leadpipe_pixel_domains = domains
                    return domains
            except Exception:
                pass  # cache is an optimization; a miss just costs one call

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"{self.LEADPIPE_API_BASE}/v1/data/pixels",
                headers={"X-API-Key": settings.leadpipe_api_key},
            )
        if resp.status_code != 200:
            # An unreadable registry says nothing about any visitor. Surfacing it
            # as "no pixel" would silently disable Leadpipe org-wide; surfacing it
            # as unavailable keeps the outage visible and the visitor retryable.
            logger.warning("leadpipe_pixel_list_error", status=resp.status_code)
            self._raise_if_transient(resp)
            raise ProviderUnavailableError(
                "leadpipe", f"pixel list HTTP {resp.status_code}"
            )

        body = resp.json()
        rows = body.get("data", []) if isinstance(body, dict) else []
        domains = {
            d.lower()
            for p in rows
            if (d := p.get("domain")) and p.get("status") == "active"
        }
        self._leadpipe_pixel_domains = domains
        if redis:
            try:
                await redis.setex(
                    self.LEADPIPE_PIXEL_CACHE_KEY,
                    self.LEADPIPE_PIXEL_CACHE_TTL,
                    json.dumps(sorted(domains)),
                )
            except Exception:
                pass
        logger.info("leadpipe_pixel_registry_loaded", active_pixels=len(domains))
        return domains

    @_http_retry
    async def _call_leadpipe_api(self, visitor: Visitor) -> dict | None:
        """Query Leadpipe for identified visitors matching this visitor's session.

        Match logic: Look for Leadpipe identifications from the same IP
        within a short time window of the visitor's last_seen timestamp.
        Retries up to 3× on transient errors (5xx, 429, timeouts).
        """
        # Scope to THIS site's pixel domain. /v1/data is account-wide and
        # paginates at 50/page; without scoping, a low-traffic site's record
        # is buried under other sites' identifications and never seen. The
        # API has NO per-IP or per-pixel filter (only email/page/timeframe/
        # domain), so `domain` is the only documented way to narrow it.
        # (limit/sort sent previously were not real params — ignored.)
        #
        # No domain used to mean "query the whole account", which reads one
        # tenant's feed while resolving another tenant's visitor. Refuse instead.
        site_domain = await self._site_domain(visitor.site_id)
        if not site_domain:
            raise ProviderNotConfiguredError(
                "leadpipe", "site has no resolvable domain"
            )

        if site_domain.lower() not in await self._leadpipe_active_domains():
            # No pixel for this domain means Leadpipe never collected anything
            # here — an empty feed is guaranteed, not informative.
            raise ProviderNotConfiguredError(
                "leadpipe", "no active pixel registered for this domain"
            )

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"{self.LEADPIPE_API_BASE}/v1/data",
                headers={"X-API-Key": settings.leadpipe_api_key},
                params={"domain": site_domain},
            )

            if resp.status_code == 404:
                logger.debug("leadpipe_no_matches")
                return None
            if resp.status_code != 200:
                logger.warning("leadpipe_api_error", status=resp.status_code,
                               detail=resp.text[:200])
                self._raise_if_transient(resp)
                # 400 = unusable request params: a real answer, so no-match.
                # Everything else (401/403 "Organization is expired" above all)
                # is the account failing, not a verdict about this visitor.
                if resp.status_code != 400:
                    raise ProviderUnavailableError(
                        "leadpipe", f"HTTP {resp.status_code}"
                    )
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
            # Counts why records were dropped, so "the feed had rows but none
            # attached" is a number instead of guesswork. The IP filter lives
            # here rather than in matching.py, so it is tallied here too.
            tally = new_rejection_tally()

            for lp_visitor in visitors_data:
                lp_email = lp_visitor.get("email")
                if not lp_email and isinstance(lp_visitor.get("emails"), list) and lp_visitor.get("emails"):
                    lp_email = lp_visitor["emails"][0]
                if not lp_email:
                    tally[REJECTION_NO_EMAIL] += 1
                    continue

                lp_ip = lp_visitor.get("ip") or lp_visitor.get("ipAddress")
                if not lp_ip or lp_ip != visitor.ip_address:
                    tally[REJECTION_IP_MISMATCH] += 1
                    continue

                matched, weak = self._record_matches_visitor(
                    lp_visitor, visitor, "leadpipe", tally=tally
                )
                if not matched:
                    continue

                person = self._parse_leadpipe_person(lp_visitor)
                if weak:
                    person["confidence_score"] = min(
                        person["confidence_score"], self._WEAK_MATCH_MAX_CONFIDENCE
                    )
                return person

            log_rejection_tally(
                "leadpipe", visitor.visitor_id, tally, len(visitors_data)
            )
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
