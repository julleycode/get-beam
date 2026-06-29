"""RB2B identity-graph provider mixin."""

import httpx
import structlog

from apps.api.config import settings
from apps.api.models.visitor import Visitor
from apps.api.services.identity_providers.base import _http_retry

logger = structlog.get_logger()


class RB2BMixin:
    @_http_retry
    async def _call_rb2b_api(self, visitor: Visitor) -> dict | None:
        """Call RB2B API Suite: IP to HEM → HEM to Business Profile.

        Two-step chain (api.rb2b.com/api/v1/):
        1. ip_to_hem: IP → Hashed Email (md5/sha256 + score)
        2. hem_to_business_profile: HEM → Full business profile
        Auth: Api-Key header. Retries up to 3× on transient errors.
        """
        rb2b_headers = {
            "Api-Key": settings.rb2b_api_key,
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=15.0) as client:
            # Step 1: IP → Hashed Email Match (HEM)
            resp = await client.post(
                "https://api.rb2b.com/api/v1/ip_to_hem",
                headers=rb2b_headers,
                json={
                    "ip_address": visitor.ip_address,
                    "user_agent": getattr(visitor, "user_agent", "") or "",
                    "include_sha256": True,
                },
            )

            if resp.status_code == 404:
                logger.debug("rb2b_no_match", ip=visitor.ip_address[:8])
                return None
            if resp.status_code == 403:
                logger.warning("rb2b_service_unavailable", detail=resp.text[:200])
                return None
            if resp.status_code != 200:
                logger.warning("rb2b_ip_error", status=resp.status_code,
                               detail=resp.text[:200])
                self._raise_if_transient(resp)
                return None

            hem_data = resp.json()
            results = hem_data.get("results", [])
            if not results:
                logger.debug("rb2b_no_hem", ip=visitor.ip_address[:8])
                return None

            best = max(results, key=lambda r: r.get("score", 0))
            hem = best.get("md5") or best.get("sha256")
            if not hem:
                logger.debug("rb2b_no_hem_hash", ip=visitor.ip_address[:8])
                return None

            # Step 2: HEM → Business Profile
            profile_resp = await client.post(
                "https://api.rb2b.com/api/v1/hem_to_business_profile",
                headers=rb2b_headers,
                json={"md5": hem},
            )

            if profile_resp.status_code != 200:
                logger.warning("rb2b_profile_error", status=profile_resp.status_code)
                self._raise_if_transient(profile_resp)
                return None

            profile = profile_resp.json()
            person = profile.get("result", profile)

            personal_emails = person.get("personal_emails") or []
            work_email = person.get("work_email")
            email = work_email or (personal_emails[0] if personal_emails else None)
            if not email:
                logger.debug("rb2b_no_email_in_profile", ip=visitor.ip_address[:8])
                return None

            # RB2B scores arrive on a 0-100 scale; ours is 0-1. Without the
            # normalization any score > 1 pinned the confidence to 0.99.
            raw_score = best.get("score", 0.9)
            if isinstance(raw_score, (int, float)) and raw_score > 1:
                raw_score = raw_score / 100.0
            return {
                "email": email,
                "full_name": person.get("full_name"),
                "title": person.get("current_title"),
                "company": person.get("current_company"),
                "linkedin_url": person.get("linkedin_url"),
                "city": person.get("city"),
                "region": person.get("state") or person.get("region"),
                "country": person.get("country", "US"),
                "confidence_score": max(0.0, min(float(raw_score), 0.99)),
            }
