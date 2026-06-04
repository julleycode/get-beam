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


class SocialPostsRequest(BaseModel):
    twitter_handle: str = ""
    linkedin_url: str = ""


@router.post("/social-posts")
@limiter.limit("6/minute")
async def demo_social_posts(request: Request, body: SocialPostsRequest) -> dict:
    """Fetch REAL recent social posts for a visitor's Twitter handle.

    Uses Twitter API v2 (if bearer token configured) to pull actual tweets.
    Never returns fake data — returns empty list if API unavailable.
    """
    posts: list[dict] = []

    handle = (body.twitter_handle or "").lstrip("@").strip()
    if not handle:
        return {"posts": [], "source": "none"}

    # Real Twitter API call
    if settings.twitter_bearer_token and not settings.mock_external_apis:
        try:
            import httpx
            async with httpx.AsyncClient(timeout=10.0) as client:
                # Resolve handle → user_id
                user_resp = await client.get(
                    f"https://api.twitter.com/2/users/by/username/{handle}",
                    headers={"Authorization": f"Bearer {settings.twitter_bearer_token}"},
                )
                if user_resp.status_code == 200:
                    user_id = user_resp.json().get("data", {}).get("id")
                    if user_id:
                        tweets_resp = await client.get(
                            f"https://api.twitter.com/2/users/{user_id}/tweets",
                            headers={"Authorization": f"Bearer {settings.twitter_bearer_token}"},
                            params={
                                "max_results": 5,
                                "tweet.fields": "created_at,text,public_metrics",
                                "exclude": "retweets",
                            },
                        )
                        if tweets_resp.status_code == 200:
                            for t in tweets_resp.json().get("data", []):
                                posts.append({
                                    "platform": "twitter",
                                    "content": t.get("text", ""),
                                    "url": f"https://x.com/{handle}/status/{t['id']}",
                                    "posted_at": t.get("created_at"),
                                    "likes": t.get("public_metrics", {}).get("like_count", 0),
                                })
                            logger.info("demo_social_posts_twitter_ok", handle=handle, count=len(posts))
                            return {"posts": posts, "source": "twitter_api"}
        except Exception as e:
            logger.warning("demo_social_posts_twitter_error", error=str(e))

    # Fallback: try Playwright browser scraping if available
    try:
        from apps.api.services.platforms.twitter_browser import TwitterBrowserPoster
        poster = TwitterBrowserPoster()
        if poster._cookie_path.exists():
            feed = await poster.fetch_timeline(limit=5)
            # Filter to posts by this handle
            for p in feed:
                if p.author_username and p.author_username.lower() == handle.lower():
                    posts.append({
                        "platform": "twitter",
                        "content": p.content or "",
                        "url": p.post_url or "",
                        "posted_at": p.posted_at.isoformat() if p.posted_at else None,
                        "likes": 0,
                    })
            if posts:
                logger.info("demo_social_posts_browser_ok", handle=handle, count=len(posts))
                return {"posts": posts, "source": "browser"}
    except Exception as e:
        logger.debug("demo_social_posts_browser_unavailable", error=str(e))

    logger.info("demo_social_posts_empty", handle=handle)
    return {"posts": [], "source": "unavailable"}


class DraftRequest(BaseModel):
    visitor_name: str = ""
    visitor_role: str = ""
    visitor_company: str = ""
    user_url: str = ""
    recent_post: str = ""  # The visitor's actual recent post to reference


@router.post("/generate-draft")
@limiter.limit("10/minute")
async def demo_generate_draft(request: Request, body: DraftRequest) -> dict:
    """Generate a personalized engagement draft using AI.

    When recent_post is provided, the draft references the visitor's
    actual social post — not generic outreach.
    """
    name = body.visitor_name.strip() or "this visitor"
    first = name.split()[0].lower() if name != "this visitor" else "there"

    # Build context-aware prompt
    if body.recent_post:
        prompt = (
            f"Write a short, casual social media reply (2-3 sentences max) to this post:\n\n"
            f'"{body.recent_post}"\n\n'
            f"The reply is from someone who runs {body.user_url or 'a SaaS product'}. "
            f"Be genuine, reference something specific from the post. "
            f"No hashtags. Lowercase casual tone. Don't start with 'hey'."
        )
    else:
        prompt = (
            f"Write a short, casual social media comment (2-3 sentences max) "
            f"to engage with {name}"
            f"{' (' + body.visitor_role + ')' if body.visitor_role else ''}"
            f"{' at ' + body.visitor_company if body.visitor_company else ''}. "
            f"The commenter runs {body.user_url or 'a SaaS product'}. "
            f"Be genuine, not salesy. No hashtags. Lowercase casual tone."
        )

    # Try Claude API
    if settings.anthropic_api_key and not settings.mock_external_apis:
        try:
            import httpx
            async with httpx.AsyncClient(timeout=8.0) as client:
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
                        "messages": [{"role": "user", "content": prompt}],
                    },
                )
                if resp.status_code == 200:
                    data = resp.json()
                    text = data.get("content", [{}])[0].get("text", "")
                    if text:
                        return {"draft": text.strip()}
        except Exception as e:
            logger.warning("demo_generate_draft_error", error=str(e))

    # Fallback: template referencing real post if available
    if body.recent_post:
        snippet = body.recent_post[:60] + ("..." if len(body.recent_post) > 60 else "")
        return {"draft": f'this resonates. "{snippet}" — been thinking about this a lot lately. would love to swap notes.'}

    company_bit = f"love what you're building at {body.visitor_company}. " if body.visitor_company else ""
    return {
        "draft": f"hey {first}! saw you checking out {body.user_url or 'our site'}. {company_bit}would love to connect."
    }
