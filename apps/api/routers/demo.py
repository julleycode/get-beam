"""Public demo endpoints used by the onboarding flow.

`POST /api/v1/demo/identify` runs the FULL identity waterfall on the
requester's own IP — identity graphs (Leadpipe, Capturify, RB2B) first
in parallel, then IP→company→person fallback. Identity graphs work on
ANY IP (residential, public WiFi, mobile) — not just business IPs.
"""

import asyncio
import re
from datetime import datetime, timezone
from types import SimpleNamespace

import structlog
from fastapi import APIRouter, HTTPException, Request, Response
from slowapi.util import get_remote_address

from pydantic import BaseModel

from sqlalchemy import select

from apps.api.config import settings
from apps.api.models.database import async_session
from apps.api.models.visitor import Visitor
from apps.api.services.rate_limiter import limiter
from apps.api.services.identity_resolver import IdentityResolver
from apps.api.services.ip_resolution import resolve_client_ip
from apps.api.services.pii import mask_email
from apps.api.services.platform_detector import detect_platform
from apps.api.services.redis_client import get_redis

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
            "platform": r["platform"],        # shopify|wordpress|wix|squarespace|webflow|nextjs|framer|unknown
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


# Global daily cap on real-provider demo calls (identity graphs + LLM tokens),
# shared across every cost-bearing demo endpoint. Bounds total spend regardless
# of per-IP slowapi limits, which key on a client-spoofable X-Forwarded-For.
# Fails OPEN (allows the call) if Redis is unreachable so the public onboarding
# demo never hard-breaks.
_DEMO_DAILY_BUDGET = 50


async def _enforce_demo_budget() -> None:
    """Raise 429 once the global daily demo budget is exhausted (fails open on Redis error)."""
    try:
        redis = get_redis()
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        key = f"demo:budget:{day}"
        count = await redis.incr(key)
        if count == 1:
            await redis.expire(key, 86400)
        if count > _DEMO_DAILY_BUDGET:
            raise HTTPException(
                status_code=429,
                detail="Demo limit reached for today — join the waitlist for full access.",
            )
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("demo_budget_check_failed_open", error=str(exc))


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
    await _enforce_demo_budget()
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

    async def _try_graph(name: str, call_fn) -> tuple[str, dict | None]:
        try:
            return name, await call_fn(stub)
        except Exception as e:
            logger.warning("demo_identity_graph_error", provider=name, error=str(e))
            return name, None

    graph_tasks = []
    if settings.leadpipe_api_key:
        graph_tasks.append(_try_graph(
            "leadpipe", resolver._call_leadpipe_api,
        ))
    if settings.capturify_api_key:
        graph_tasks.append(_try_graph(
            "capturify", resolver._call_capturify_api,
        ))
    if settings.rb2b_api_key:
        graph_tasks.append(_try_graph(
            "rb2b", resolver._call_rb2b_api,
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


class JourneyBody(BaseModel):
    fingerprint: str | None = None


@router.post("/journey")
@limiter.limit("12/minute")
async def demo_journey(request: Request, body: JourneyBody = JourneyBody()) -> dict:
    """Replay the caller's real visit on getbeam.fyi inside onboarding.

    Sample-data users have no site of their own, so the onboarding sends them
    to getbeam.fyi (which runs the Beam pixel). This matches their browser
    fingerprint — the same ``fp2_`` value the pixel emits — to the visitor
    row(s) the pixel just recorded, then returns the pages they browsed in
    order with how long they spent on each.

    Durations live in separate ``time_on_page`` event rows keyed by url (the
    pixel fires them on page leave), so we merge those seconds onto each
    ``pageview``. Read-only, scoped to the last hour, capped at 8 pages.
    """
    fp = (body.fingerprint or "").strip()
    if not fp.startswith("fp2_"):
        return {"matched": False, "pages": []}

    # Shared implementation with the authed onboarding canary. site_id is
    # deliberately NOT passed here: this public path keeps its historical
    # unscoped fingerprint match so the static funnel behaves identically.
    # New callers must scope (see services/onboarding_canary.fetch_journey).
    from apps.api.services.onboarding_canary import fetch_journey

    try:
        async with async_session() as db:
            pages = await fetch_journey(db, fp)
    except Exception as e:  # noqa: BLE001 — demo never 500s the onboarding
        logger.debug("demo_journey_failed", error=str(e))
        return {"matched": False, "pages": []}

    logger.info("demo_journey", fp=fp[:12], pages=len(pages))
    return {"matched": bool(pages), "pages": pages}


# ───────────────────────── public canary (static funnel) ─────────────────────
# Unauthenticated twin of POST /api/v1/onboarding/canary. Same shared builders
# (services/onboarding_canary.py), same response shape, no forked logic.
#
# Security posture — every line here is load-bearing:
#
# * THE ONLY IP EVER RESOLVED IS THE CALLER'S OWN, via
#   ``ip_resolution.resolve_client_ip``. An IP is never accepted from the body
#   or the query string; ``CanaryPublicBody`` has exactly one field and Pydantic
#   drops the rest. Accepting a caller-supplied IP would turn this into a free
#   geolocation-lookup API for arbitrary addresses.
#   It also does NOT use ``demo._client_ip`` (used by the older demo routes),
#   which trusts the first X-Forwarded-For entry with no hop check and is
#   therefore client-spoofable.
# * The journey is SCOPED to ``settings.beam_self_site_id``. The neighbouring
#   ``demo_journey`` matches ``Visitor.fingerprint`` with no site predicate and
#   is cross-tenant by construction — the exact class of bug commit 7e798ab
#   ("close cross-tenant PII leak on /demo") had to fix once already. Do not
#   copy that call shape here.
# * No ip / site_id / visitor_id / fingerprint in the response body. The IP is
#   logged truncated (``ip[:8]``), as the rest of this module does.
# * No paid provider is called, so ``_enforce_demo_budget`` is deliberately NOT
#   applied: a free geo lookup must not be able to exhaust the identity-graph
#   budget that ``/identify`` depends on.
# * Flag off => 404 on both routes (dormant, not merely disabled).
_PUBLIC_CANARY_SURFACE = "public_onboarding_canary"

# The static funnel polls: 2s for the first 20s, then 4s to a 90s deadline —
# ~20 calls inside any single minute, ~27 over a full run. 40/minute leaves room
# for one mid-run reload (which restarts the poll, since the static funnel has no
# resume) while staying far below anything useful for bulk lookups. The authed
# twin uses 30/minute; it can afford the tighter bound because a signed-in user's
# flow state survives a reload.
_PUBLIC_CANARY_RATE = "40/minute"


def _require_location_reveal() -> None:
    if not settings.location_reveal_enabled:
        # Dormant: do not reveal that the endpoint exists when disabled.
        raise HTTPException(status_code=404, detail="Not Found")


class CanaryPublicBody(BaseModel):
    """One field, on purpose. Any ``ip``/``site_id`` a caller adds is ignored."""

    fingerprint: str | None = None


@router.post("/canary")
@limiter.limit(_PUBLIC_CANARY_RATE)
async def demo_canary(request: Request, body: CanaryPublicBody = CanaryPublicBody()) -> dict:
    """Public "we caught you": where the CALLER is, and what they just read.

    Never 500s — a provider failure degrades to ``geo: null`` rather than an
    error, because this runs inside a chat the user cannot retry.
    """
    _require_location_reveal()

    from apps.api.services.geoip import resolve_geoip_full
    from apps.api.services.onboarding_canary import (
        build_geo,
        build_network,
        fetch_journey,
    )

    fp = (body.fingerprint or "").strip()
    ip = resolve_client_ip(request)

    pages: list[dict] = []
    if fp:
        try:
            async with async_session() as db:
                pages = await fetch_journey(db, fp, site_id=settings.beam_self_site_id)
        except Exception as e:  # noqa: BLE001 — the reveal never 500s the funnel
            logger.debug("demo_canary_journey_failed", error=str(e))

    geo_raw = None
    reason: str | None = None
    try:
        geo_raw = await resolve_geoip_full(ip)
    except Exception as e:  # noqa: BLE001 — defensive; resolve_geoip_full swallows already
        logger.debug("demo_canary_geo_failed", ip=ip[:8], error=str(e))
    if geo_raw is None:
        reason = "provider_unavailable"

    geo = build_geo(geo_raw)
    network = build_network(ip, geo_raw) if geo_raw is not None else None

    logger.info(
        "demo_canary", ip=ip[:8], fp=fp[:12], pages=len(pages), has_geo=geo is not None
    )

    result: dict = {
        "landed": bool(pages),
        "pages": pages,
        "geo": geo,
        "network": network,
    }
    if reason:
        result["reason"] = reason
    return result


class CanaryFeedbackBody(BaseModel):
    reasons: list[str] = []
    note: str | None = None
    shown: dict = {}
    fingerprint: str | None = None


@router.post("/identity-feedback", status_code=204)
@limiter.limit("12/minute")
async def demo_identity_feedback(request: Request, body: CanaryFeedbackBody) -> Response:
    """Record a "not quite" answer from the public funnel. 204 always.

    The client submits optimistically and advances in the same tick, so this must
    never be something the funnel can block on. Unknown reasons are dropped
    rather than stored, so the counts stay analysable — the same anti-fabrication
    rule the authed twin applies.
    """
    _require_location_reveal()

    from apps.api.models.identity_feedback import (
        ANONYMOUS_USER_ID,
        FEEDBACK_REASONS,
        NOTE_MAX_CHARS,
        IdentityFeedback,
    )

    reasons = [r for r in (body.reasons or []) if r in FEEDBACK_REASONS]
    note = (body.note or "").strip()[:NOTE_MAX_CHARS] or None

    try:
        async with async_session() as db:
            db.add(
                IdentityFeedback(
                    # No account exists at this beat — documented sentinel, not a
                    # fabricated user. `surface` is the real discriminator.
                    user_id=ANONYMOUS_USER_ID,
                    site_id=None,
                    fingerprint=(body.fingerprint or None),
                    surface=_PUBLIC_CANARY_SURFACE,
                    shown=(body.shown if isinstance(body.shown, dict) else {}),
                    reasons=reasons,
                    note=note,
                )
            )
            await db.commit()
    except Exception as e:  # noqa: BLE001 — a feedback write never breaks the funnel
        logger.warning("demo_identity_feedback_failed", error=str(e))

    logger.info("demo_identity_feedback", reasons=reasons, has_note=bool(note))
    return Response(status_code=204)


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
    await _enforce_demo_budget()
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
    await _enforce_demo_budget()
    posts: list[dict] = []

    handle = (body.twitter_handle or "").lstrip("@").strip()
    if not handle:
        return {"posts": [], "source": "none"}

    # Real Twitter API call
    if settings.twitter_bearer_token:
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
    await _enforce_demo_budget()
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
    if settings.anthropic_api_key:
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
    if settings.openrouter_api_key:
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


_X_HANDLE_INVALID = re.compile(r"[^A-Za-z0-9_]")


def _normalize_x_handle(raw: str | None) -> str | None:
    """Normalize a user-entered X handle to a bare username (no '@', no URL).

    Accepts '@foo', 'foo', 'x.com/foo', 'https://twitter.com/foo?ref=1', etc.
    Returns the lowercase-preserving username with only [A-Za-z0-9_], capped at
    39 chars to fit the column, or None when nothing usable remains. Entering a
    handle is the opt-in to the public Founders Wall.
    """
    if not raw:
        return None
    h = raw.strip()
    h = re.sub(r"^https?://", "", h, flags=re.IGNORECASE)
    h = re.sub(r"^(www\.)?(x\.com|twitter\.com)/", "", h, flags=re.IGNORECASE)
    h = h.split("/")[0].split("?")[0]
    h = h.lstrip("@").strip()
    h = _X_HANDLE_INVALID.sub("", h)
    return h[:39] or None


class WaitlistRequest(BaseModel):
    email: str
    site_url: str | None = None
    x_handle: str | None = None


@router.post("/waitlist")
@limiter.limit("5/minute")
async def join_waitlist(request: Request, body: WaitlistRequest) -> dict:
    """Collect waitlist email for private beta."""
    email = body.email.strip().lower()
    if not email or "@" not in email:
        return {"status": "invalid"}

    x_handle = _normalize_x_handle(body.x_handle)

    logger.info("waitlist_signup", email=mask_email(email))

    # Store in waitlist_signups table (upsert: ignore duplicate emails)
    try:
        from apps.api.models.database import get_db
        from apps.api.models.waitlist import WaitlistSignup

        async for db in get_db():
            # Check for existing signup
            from sqlalchemy import select as sa_select
            result = await db.execute(
                sa_select(WaitlistSignup).where(WaitlistSignup.email == email)
            )
            existing = result.scalar_one_or_none()
            if existing:
                # Backfill site_url / x_handle if newly provided and not already set
                changed = False
                if body.site_url and not existing.site_url:
                    existing.site_url = body.site_url
                    changed = True
                if x_handle and not existing.x_handle:
                    existing.x_handle = x_handle
                    changed = True
                if changed:
                    await db.commit()
                break

            entry = WaitlistSignup(
                email=email,
                site_url=body.site_url or None,
                x_handle=x_handle,
            )
            db.add(entry)
            await db.commit()
            break
    except Exception as e:
        logger.warning("waitlist_db_error", error=str(e))

    # Send confirmation email to subscriber
    try:
        from apps.api.services.email_sender import EmailSender
        sender = EmailSender()

        await sender.send(
            to_email=email,
            subject="you're on the list — beam",
            body_html="""
<div style="font-family: 'Inter', -apple-system, sans-serif; max-width: 520px; margin: 0 auto; color: #2b2530;">
  <p style="font-size: 16px; line-height: 1.7; color: #4a3f50;">hey,</p>
  <p style="font-size: 16px; line-height: 1.7; color: #4a3f50;">
    you're on the beam waitlist. we'll let you know as soon as your spot opens up.
  </p>
  <p style="font-size: 16px; line-height: 1.7; color: #4a3f50;">
    beam shows you exactly who's visiting your site — real people, real profiles — so you can
    follow up while they're still warm.
  </p>
  <p style="font-size: 16px; line-height: 1.7; color: #4a3f50;">
    sit tight. it won't be long.
  </p>
  <p style="font-size: 15px; line-height: 1.7; color: #FF3366; font-style: italic; margin-top: 24px;">
    &mdash; julley, beam
  </p>
</div>
""",
            from_name="Beam",
            from_email="hello@getbeam.fyi",
            branding=True,
        )
    except Exception as e:
        logger.warning("waitlist_confirmation_email_failed", email=mask_email(email), error=str(e))

    # Send notification to admin
    try:
        sender = EmailSender()
        site_info = f" (site: {body.site_url})" if body.site_url else ""
        await sender.send(
            to_email="tranthai.work@gmail.com",
            subject=f"New waitlist signup: {email}",
            body_html=f"""
<div style="font-family: 'Inter', -apple-system, sans-serif; max-width: 520px; margin: 0 auto; color: #2b2530;">
  <p style="font-size: 16px; line-height: 1.7; color: #4a3f50;">
    <strong>{email}</strong> just joined the Beam waitlist.{site_info}
  </p>
  <p style="font-size: 14px; color: #b8a0a8;">
    <a href="https://getbeam.fyi/dashboard/waitlist">Review in dashboard &rarr;</a>
  </p>
</div>
""",
            from_name="Beam",
            from_email="noreply@getbeam.fyi",
        )
    except Exception:
        pass

    return {"status": "ok"}


BETA_TOTAL_SLOTS = 20


@router.get("/beta-slots")
async def beta_slots() -> dict:
    """Public endpoint: how many private-beta slots remain.

    Counts anyone admitted — both 'approved' (invited with email) and 'granted'
    (slot reserved without email) — so inviting real users honestly decrements
    the public "spots left" counter. Pending signups do not affect it.
    """
    try:
        from apps.api.models.waitlist import WaitlistSignup
        async with async_session() as db:
            result = await db.execute(
                select(WaitlistSignup).where(
                    WaitlistSignup.status.in_(["granted", "approved"])
                )
            )
            taken = len(result.scalars().all())
    except Exception:
        taken = 0

    remaining = max(0, BETA_TOTAL_SLOTS - taken)
    return {"total": BETA_TOTAL_SLOTS, "taken": taken, "remaining": remaining}


FOUNDER_WALL_SIZE = 100


def _founder_initials(full_name: str | None, email: str) -> str:
    """Two public-safe initials for a wall tile, from name or email local part."""
    source = (full_name or "").strip() or email.split("@", 1)[0]
    parts = [p for p in re.split(r"[^A-Za-z]+", source) if p]
    if len(parts) >= 2:
        return (parts[0][0] + parts[1][0]).upper()
    if parts:
        return parts[0][:2].upper()
    return "BM"


@router.get("/founders")
async def founders_wall() -> dict:
    """Public endpoint: the Founders Wall roster.

    Two sources, in order:
    1. Waitlist signups that opted in with an X handle (earliest first). The
       frontend resolves avatars via unavatar.io and links to x.com/<handle>.
    2. Registered accounts (Clerk-synced users table, earliest first) that are
       not already on the wall — initials derived from full name or email local
       part, plus their Clerk profile image when one exists. Exposes ONLY
       initials + the img.clerk.com avatar URL (never email/name).

    Fails soft: any DB error yields an empty roster so the landing page renders
    a clean all-empty wall instead of breaking.
    """
    founders: list[dict] = []
    claimed = 0
    try:
        from apps.api.models.user import User
        from apps.api.models.waitlist import WaitlistSignup

        async with async_session() as db:
            wl_result = await db.execute(
                select(WaitlistSignup.email, WaitlistSignup.x_handle)
                .order_by(WaitlistSignup.created_at.asc())
            )
            wl_rows = wl_result.all()
            waitlist_emails = {(e or "").lower() for e, _ in wl_rows}

            position = 0
            tiled_emails: set[str] = set()
            for email, handle in wl_rows:
                if not handle or position >= FOUNDER_WALL_SIZE:
                    continue
                founders.append({"position": position, "handle": handle})
                tiled_emails.add((email or "").lower())
                position += 1

            user_result = await db.execute(
                select(User.email, User.full_name, User.avatar_url)
                .order_by(User.created_at.asc())
                .limit(FOUNDER_WALL_SIZE)
            )
            extra_claimed = 0
            for email, full_name, avatar_url in user_result.all():
                key = (email or "").lower()
                if not key or key in tiled_emails:
                    continue
                if position < FOUNDER_WALL_SIZE:
                    entry = {
                        "position": position,
                        "initials": _founder_initials(full_name, key),
                    }
                    if avatar_url:
                        entry["avatar"] = avatar_url
                    founders.append(entry)
                    tiled_emails.add(key)
                    position += 1
                # Waitlist signups are already counted below; only accounts
                # that never went through the waitlist add to the counter.
                if key not in waitlist_emails:
                    extra_claimed += 1

            claimed = min(len(wl_rows) + extra_claimed, FOUNDER_WALL_SIZE)
    except Exception as exc:
        logger.warning("founders_wall_query_failed", error=str(exc))
        return {"spots": FOUNDER_WALL_SIZE, "claimed": 0, "founders": []}

    return {"spots": FOUNDER_WALL_SIZE, "claimed": claimed, "founders": founders}
