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

from apps.api.config import settings
from apps.api.routers.social_auth import limiter
from apps.api.services.identity_resolver import IdentityResolver
from apps.api.services.platform_detector import detect_platform

logger = structlog.get_logger()

router = APIRouter(tags=["demo"])


@router.get("/clerk-config")
async def demo_clerk_config() -> dict:
    """Expose the Clerk publishable key so the static onboarding can load ClerkJS.

    Publishable keys (pk_test_/pk_live_) are designed to be public — they ship in
    the client bundle. Returns null when Clerk isn't configured so the onboarding
    falls back to the legacy email/password signup.
    """
    return {"publishable_key": settings.clerk_publishable_key or None}


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


class EmailIdentifyRequest(BaseModel):
    email: str


@router.post("/identify-by-email")
@limiter.limit("6/minute")
async def demo_identify_by_email(request: Request, body: EmailIdentifyRequest) -> dict:
    """Enrich a real person by email — fallback when IP doesn't resolve.

    Uses the same PDL enrichment pipeline as production. Returns genuine,
    verifiable data (LinkedIn URL, Twitter handle, job title, company) —
    never fabricated profiles.
    """
    email = body.email.strip().lower()
    base: dict = {"matched": False, "email": email}

    if not email or "@" not in email:
        return base

    try:
        from apps.api.services.enricher import Enricher
        prof = await Enricher(None)._enrich_pdl(email)
        name = (prof.get("full_name") or "").strip() if prof else ""
        has_identity = bool(name or (prof and prof.get("linkedin_url")))
        if prof and has_identity:
            base.update({
                "matched": True,
                "level": "person",
                "full_name": name or None,
                "email": email,
                "job_title": prof.get("job_title"),
                "company_name": prof.get("company_name"),
                "company_domain": prof.get("company_domain"),
                "linkedin_url": prof.get("linkedin_url"),
                "twitter_handle": prof.get("twitter_handle"),
                "city": prof.get("city"),
                "country": prof.get("country"),
            })
    except Exception as e:
        logger.warning("demo_identify_by_email_error", error=str(e))

    logger.info("demo_identify_by_email", matched=base["matched"])
    return base


class DraftRequest(BaseModel):
    visitor_name: str = ""
    visitor_role: str = ""
    visitor_company: str = ""
    user_url: str = ""


@router.post("/generate-draft")
@limiter.limit("10/minute")
async def demo_generate_draft(request: Request, body: DraftRequest) -> dict:
    """Generate a personalized engagement draft using AI.

    Uses Claude to write a short, natural comment/reply that the user
    could send to the identified visitor on social media.
    """
    name = body.visitor_name.strip() or "this visitor"
    first = name.split()[0].lower() if name != "this visitor" else "there"

    # Try Claude API
    if settings.anthropic_api_key and not settings.mock_external_apis:
        try:
            import httpx
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={
                        "x-api-key": settings.anthropic_api_key,
                        "anthropic-version": "2023-06-01",
                        "content-type": "application/json",
                    },
                    json={
                        "model": "claude-sonnet-4-20250514",
                        "max_tokens": 150,
                        "messages": [{"role": "user", "content": (
                            f"Write a short, casual social media comment (2-3 sentences max) "
                            f"that someone could post to engage with {name}"
                            f"{' (' + body.visitor_role + ')' if body.visitor_role else ''}"
                            f"{' at ' + body.visitor_company if body.visitor_company else ''}. "
                            f"The commenter runs {body.user_url or 'a SaaS product'}. "
                            f"Be genuine, not salesy. No hashtags. Lowercase casual tone."
                        )}],
                    },
                )
                if resp.status_code == 200:
                    data = resp.json()
                    text = data.get("content", [{}])[0].get("text", "")
                    if text:
                        return {"draft": text.strip()}
        except Exception as e:
            logger.warning("demo_generate_draft_error", error=str(e))

    # Fallback: template-based draft
    company_bit = f"love what you're building at {body.visitor_company}. " if body.visitor_company else ""
    return {
        "draft": f"hey {first}! saw you checking out {body.user_url or 'our site'}. {company_bit}would love to connect and swap notes."
    }
