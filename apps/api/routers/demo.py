"""Public demo endpoints used by the onboarding flow.

`POST /api/v1/demo/identify` runs the FULL identity waterfall on the
requester's own IP — identity graphs (Leadpipe, Capturify, RB2B) first
in parallel, then IP→company→person fallback. Identity graphs work on
ANY IP (residential, public WiFi, mobile) — not just business IPs.
"""

import asyncio
from types import SimpleNamespace

import structlog
from fastapi import APIRouter, Request
from slowapi.util import get_remote_address

from pydantic import BaseModel

from sqlalchemy import select

from apps.api.config import settings
from apps.api.models.database import async_session
from apps.api.models.visitor import Visitor
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


class IdentifyBody(BaseModel):
    fingerprint: str | None = None


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
@limiter.limit("6/minute")
async def demo_identify(request: Request, body: IdentifyBody = IdentifyBody()) -> dict:
    """Run the FULL identity waterfall on the caller's IP (read-only).

    Identity graphs (Leadpipe, Capturify, RB2B) run first IN PARALLEL —
    they work on ANY IP including residential and public WiFi. Only falls
    back to IP→company→person if all identity graphs miss.

    When ``fingerprint`` is provided (from the onboarding page), we also
    check whether the pixel already recorded a visit with that same
    fingerprint — proving the pixel detected the onboarding user.
    """
    ip = _client_ip(request)
    base: dict = {"matched": False, "ip": ip, "providers_tried": []}
    if not ip:
        return base

    resolver = IdentityResolver(db=None)
    stub = SimpleNamespace(
        ip_address=ip, country_code=None, visitor_id="demo", site_id="demo",
        company_domain=None, pages_visited=[],
    )

    # ── Pre-check: fingerprint match against recent pixel events ──
    fp_matched = False
    if body.fingerprint and body.fingerprint.startswith("fp2_"):
        try:
            async with async_session() as db:
                result = await db.execute(
                    select(Visitor.visitor_id, Visitor.ip_address)
                    .where(
                        Visitor.fingerprint == body.fingerprint,
                    )
                    .order_by(Visitor.last_seen.desc())
                    .limit(1)
                )
                pixel_visitor = result.first()
                if pixel_visitor:
                    fp_matched = True
                    base["fingerprint_matched"] = True
                    base["providers_tried"].append("fingerprint")
                    logger.info("demo_fingerprint_match", fp=body.fingerprint[:12])
        except Exception as e:
            logger.debug("demo_fingerprint_check_failed", error=str(e))

    # ── Step 0: Identity Graphs in parallel (works on ANY IP) ──

    async def _try_graph(name: str, call_fn, mock_fn) -> tuple[str, dict | None]:
        try:
            if settings.mock_external_apis:
                return name, mock_fn(stub)
            return name, await call_fn(stub)
        except Exception as e:
            logger.warning("demo_identity_graph_error", provider=name, error=str(e))
            return name, None

    graph_tasks = []
    if settings.leadpipe_api_key or settings.mock_external_apis:
        graph_tasks.append(_try_graph(
            "leadpipe", resolver._call_leadpipe_api, resolver._mock_leadpipe_response,
        ))
    if settings.capturify_api_key or settings.mock_external_apis:
        graph_tasks.append(_try_graph(
            "capturify", resolver._call_capturify_api, resolver._mock_capturify_response,
        ))
    if settings.rb2b_api_key or settings.mock_external_apis:
        graph_tasks.append(_try_graph(
            "rb2b", resolver._call_rb2b_api, resolver._mock_rb2b_response,
        ))

    best_match: dict | None = None
    best_provider: str = ""

    if graph_tasks:
        results = await asyncio.gather(*graph_tasks, return_exceptions=True)
        for result in results:
            if isinstance(result, BaseException):
                continue
            name, data = result
            base["providers_tried"].append(name)
            if data and data.get("email"):
                score = data.get("confidence_score", 0)
                if not best_match or score > best_match.get("confidence_score", 0):
                    best_match = data
                    best_provider = name

    if best_match:
        base.update({
            "matched": True,
            "level": "person",
            "full_name": best_match.get("full_name"),
            "email": best_match.get("email"),
            "city": best_match.get("city"),
            "country": best_match.get("country"),
            "resolution_provider": best_provider,
        })
        try:
            from apps.api.services.enricher import Enricher
            prof = await Enricher(None)._enrich_pdl(best_match["email"])
            if prof:
                base.update({
                    "job_title": prof.get("job_title"),
                    "company_name": prof.get("company_name"),
                    "company_domain": prof.get("company_domain"),
                    "linkedin_url": prof.get("linkedin_url"),
                    "twitter_handle": prof.get("twitter_handle"),
                })
        except Exception as e:
            logger.warning("demo_identify_enrich_error", error=str(e))

        logger.info("demo_identify", ip=ip[:8], level="person", matched=True, provider=best_provider)
        return base

    # ── Steps 1-4: IP → Company → Person fallback ──

    base["providers_tried"].extend(["pdl_ip", "ipinfo"])
    try:
        domain = await resolver._call_pdl_ip_enrich(stub)
        if not domain:
            domain = await resolver._call_ipinfo_api(stub)
    except Exception as e:
        logger.warning("demo_identify_ip_error", error=str(e))
        domain = None

    base["country"] = getattr(stub, "country_code", None)

    if not domain:
        if fp_matched:
            base.update({"matched": True, "level": "device", "resolution_provider": "fingerprint"})
            logger.info("demo_identify", ip=ip[:8], level="device", matched=True)
        return base

    base["company_domain"] = domain
    base["providers_tried"].extend(["hunter", "apollo"])

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

    # Try Claude API (direct)
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
            logger.warning("demo_generate_draft_anthropic_error", error=str(e))

    # Try OpenRouter (fallback — supports 100+ models)
    if settings.openrouter_api_key and not settings.mock_external_apis:
        try:
            import httpx
            async with httpx.AsyncClient(timeout=8.0) as client:
                resp = await client.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {settings.openrouter_api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": "anthropic/claude-sonnet-4-20250514",
                        "max_tokens": 150,
                        "messages": [{"role": "user", "content": prompt}],
                    },
                )
                if resp.status_code == 200:
                    data = resp.json()
                    text = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                    if text:
                        return {"draft": text.strip()}
        except Exception as e:
            logger.warning("demo_generate_draft_openrouter_error", error=str(e))

    # Fallback: template referencing real post if available
    if body.recent_post:
        snippet = body.recent_post[:60] + ("..." if len(body.recent_post) > 60 else "")
        return {"draft": f'this resonates. "{snippet}" — would love to swap notes on this.'}

    site = body.user_url or "your site"
    if name != "this visitor":
        return {"draft": f"saw {first} checking out {site}. would love to connect and swap notes."}
    return {
        "draft": f"someone's been checking out your pricing page on {site}. this is what beam would draft based on their social posts and your tone."
    }
