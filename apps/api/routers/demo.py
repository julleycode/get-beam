"""Public demo endpoints used by the onboarding flow.

`POST /api/v1/demo/identify` runs the REAL deployed identity waterfall
(PDL IP Enrich → IPinfo → company domain → Hunter/Apollo contact) on the
requester's own IP, so the onboarding "wow" reveal shows genuine data —
not a fabricated profile. Residential IPs won't resolve (returns matched:false),
and the frontend falls back to a clearly-labelled sample.
"""

from types import SimpleNamespace

import structlog
from fastapi import APIRouter, Request
from slowapi.util import get_remote_address

from pydantic import BaseModel

from apps.api.routers.social_auth import limiter
from apps.api.services.identity_resolver import IdentityResolver
from apps.api.services.platform_detector import detect_platform

logger = structlog.get_logger()

router = APIRouter(tags=["demo"])


class DetectBody(BaseModel):
    url: str


@router.post("/detect-platform")
@limiter.limit("12/minute")
async def demo_detect_platform(request: Request, body: DetectBody) -> dict:
    """Public, real platform detection for onboarding (fetches the site's HTML).

    Same engine the dashboard uses — just without the auth gate, since the
    onboarding runs before the account exists.
    """
    try:
        r = await detect_platform(body.url)
        return {
            "platform": r["platform"],        # shopify|wordpress|wix|squarespace|webflow|unknown
            "confidence": r["confidence"],
            "has_gtm": r["has_gtm"],
            "gtm_id": r["gtm_id"],
        }
    except Exception as e:
        logger.warning("demo_detect_platform_error", error=str(e))
        return {"platform": "unknown", "confidence": 0.0, "has_gtm": False, "gtm_id": None}


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else ""


@router.post("/identify")
@limiter.limit("6/minute")  # protect the paid PDL/Hunter/Apollo calls from abuse
async def demo_identify(request: Request) -> dict:
    """Run the real IP→company→person waterfall on the caller's IP (read-only)."""
    ip = _client_ip(request)
    base: dict = {"matched": False, "ip": ip}
    if not ip:
        return base

    # Reuse the production resolver's read-only call methods (no DB writes / logs).
    resolver = IdentityResolver(db=None)
    stub = SimpleNamespace(
        ip_address=ip, country_code=None, visitor_id="demo", site_id="demo",
        company_domain=None, pages_visited=[],
    )

    try:
        # 1) IP → company domain (PDL IP Enrich, then IPinfo fallback)
        domain = await resolver._call_pdl_ip_enrich(stub)
        if not domain:
            domain = await resolver._call_ipinfo_api(stub)
    except Exception as e:  # never break onboarding on an upstream hiccup
        logger.warning("demo_identify_ip_error", error=str(e))
        domain = None

    base["country"] = getattr(stub, "country_code", None)

    if not domain:
        # Residential / hosting / no-match — frontend shows a labelled sample.
        return base

    base["company_domain"] = domain

    # 2) company domain → a real contact (Hunter, then Apollo)
    contact = None
    try:
        contact = await resolver._call_hunter_api(domain)
        if not contact:
            contact = await resolver._call_apollo_api(domain)
    except Exception as e:
        logger.warning("demo_identify_contact_error", error=str(e))

    if contact and contact.get("email"):
        base.update({
            "matched": True,
            "level": "person",
            "full_name": contact.get("full_name"),
            "email": contact.get("email"),
            "company_domain": domain,
            "city": contact.get("city"),
            "country": contact.get("country") or base.get("country"),
        })
        # Genuine Tier-1 enrichment: email → job title + LinkedIn/Twitter (same as prod)
        try:
            from apps.api.services.enricher import Enricher
            prof = await Enricher(None)._enrich_pdl(contact["email"])
            if prof:
                base.update({
                    "job_title": prof.get("job_title"),
                    "company_name": prof.get("company_name"),
                    "linkedin_url": prof.get("linkedin_url"),
                    "twitter_handle": prof.get("twitter_handle"),
                })
        except Exception as e:
            logger.warning("demo_identify_enrich_error", error=str(e))
    else:
        # Company resolved but no person — still a real, honest result.
        base.update({"matched": True, "level": "company", "company_domain": domain})

    logger.info("demo_identify", ip=ip[:8], level=base.get("level"), matched=base["matched"])
    return base
