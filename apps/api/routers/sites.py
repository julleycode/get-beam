import json
import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.config import settings
from apps.api.models.database import get_db
from apps.api.models.site import Site
from apps.api.models.user import User
from apps.api.dependencies import get_current_user
from apps.api.schemas.sites import (
    PlatformDetectRequest,
    PlatformDetectResponse,
    PixelVerifyResponse,
    ShopifyConnectRequest,
    SiteCreate,
    SiteOut,
    SitePixelSnippet,
)
from apps.api.services.platform_detector import detect_platform
from apps.api.services.pixel_verifier import verify_pixel
from apps.api.services.wordpress_plugin_generator import generate_plugin_zip

router = APIRouter()
logger = structlog.get_logger()


def _generate_site_id() -> str:
    return f"site_{uuid.uuid4().hex[:12]}"


# ──────────────────────────── Existing CRUD ────────────────────────────


def _normalize_url(raw: str) -> str:
    """Normalize URL for dedup: lowercase, strip trailing /, strip www."""
    url = raw.strip().rstrip("/").lower()
    for prefix in ("https://www.", "http://www."):
        if url.startswith(prefix):
            url = url.replace(prefix, prefix.replace("www.", ""), 1)
    return url


@router.post("/", response_model=SiteOut)
async def create_site(
    body: SiteCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SiteOut:
    normalized_url = _normalize_url(body.url)

    # Check if ANY user already created a site for this URL
    result = await db.execute(
        select(Site).where(Site.url == normalized_url).order_by(Site.created_at)
    )
    existing = result.scalars().first()
    if not existing:
        # Also check with www. variant and trailing slash variants
        variants = {body.url.strip().rstrip("/").lower(), normalized_url}
        result = await db.execute(
            select(Site).where(Site.url.in_(variants)).order_by(Site.created_at)
        )
        existing = result.scalars().first()

    if existing:
        if existing.user_id != user.id:
            # Another user already owns this URL — refuse to reassign
            raise HTTPException(
                status_code=409,
                detail="This site URL is already registered to another account.",
            )
        # Same user already has this site — return it as-is (dedup)
        return SiteOut.model_validate(existing)

    site = Site(
        site_id=_generate_site_id(),
        user_id=user.id,
        name=body.name,
        url=normalized_url,
        description=body.description,
        category=body.category,
    )
    db.add(site)
    await db.commit()
    await db.refresh(site)
    return SiteOut.model_validate(site)


@router.get("/", response_model=list[SiteOut])
async def list_sites(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[SiteOut]:
    result = await db.execute(select(Site).where(Site.user_id == user.id))
    sites = result.scalars().all()
    return [SiteOut.model_validate(s) for s in sites]


@router.get("/{site_id}", response_model=SiteOut)
async def get_site(
    site_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SiteOut:
    result = await db.execute(
        select(Site).where(Site.site_id == site_id, Site.user_id == user.id)
    )
    site = result.scalar_one_or_none()
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")
    return SiteOut.model_validate(site)


@router.get("/{site_id}/pixel", response_model=SitePixelSnippet)
async def get_pixel_snippet(
    site_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SitePixelSnippet:
    result = await db.execute(
        select(Site).where(Site.site_id == site_id, Site.user_id == user.id)
    )
    site = result.scalar_one_or_none()
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")

    # Build identity providers list for multi-provider pixel stacking
    providers: list[dict[str, str]] = []

    # Leadpipe: prefer per-site pixel ID, fall back to global default
    leadpipe_pixel_id = (
        getattr(site, "leadpipe_pixel_id", None)
        or (settings.leadpipe_default_pixel_id if settings.leadpipe_api_key or settings.leadpipe_default_pixel_id else None)
    )
    if leadpipe_pixel_id:
        providers.append({"type": "leadpipe", "id": leadpipe_pixel_id})

    if settings.capturify_pixel_id:
        providers.append({"type": "capturify", "id": settings.capturify_pixel_id})

    if settings.fullcontact_pixel_id:
        providers.append({"type": "fullcontact", "id": settings.fullcontact_pixel_id})

    if settings.customers_ai_pixel_id:
        providers.append({"type": "customers_ai", "id": settings.customers_ai_pixel_id})

    providers_attr = ""
    if providers:
        providers_json = json.dumps(providers, separators=(",", ":"))
        providers_attr = f" data-identity-providers='{providers_json}'"

    snippet = (
        f'<script src="{settings.api_base_url}/pixel/tracker.js" '
        f'data-site="{site.site_id}" data-api="{settings.api_base_url}"'
        f'{providers_attr} defer></script>'
    )
    return SitePixelSnippet(site_id=site.site_id, snippet=snippet)


# ──────────────────────── Platform Detection ───────────────────────────


@router.post("/detect-platform", response_model=PlatformDetectResponse)
async def detect_platform_endpoint(
    body: PlatformDetectRequest,
    user: User = Depends(get_current_user),
) -> PlatformDetectResponse:
    """Auto-detect which platform a website is built on."""
    result = await detect_platform(body.url)
    return PlatformDetectResponse(
        platform=result["platform"],
        confidence=result["confidence"],
        has_gtm=result["has_gtm"],
        gtm_id=result["gtm_id"],
    )


# ──────────────────────── Pixel Verification ───────────────────────────


@router.post("/{site_id}/verify-pixel", response_model=PixelVerifyResponse)
async def verify_pixel_endpoint(
    site_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PixelVerifyResponse:
    """Verify that the tracking pixel is installed on the site."""
    result = await db.execute(
        select(Site).where(Site.site_id == site_id, Site.user_id == user.id)
    )
    site = result.scalar_one_or_none()
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")

    verify_result = await verify_pixel(site.url, site_id)

    if verify_result["verified"] and not site.pixel_verified:
        site.pixel_verified = True
        await db.commit()

    return PixelVerifyResponse(
        site_id=site_id,
        status=verify_result["status"],
        verified=verify_result["verified"],
        message=verify_result["message"],
    )


# ──────────────────────── WordPress Plugin ─────────────────────────────


@router.get("/{site_id}/wordpress-plugin")
async def download_wordpress_plugin(
    site_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Download auto-generated WordPress plugin with pre-configured site ID."""
    result = await db.execute(
        select(Site).where(Site.site_id == site_id, Site.user_id == user.id)
    )
    site = result.scalar_one_or_none()
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")

    zip_bytes = generate_plugin_zip(site_id, settings.api_base_url)

    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={
            "Content-Disposition": f"attachment; filename=beam-pixel-{site_id}.zip"
        },
    )


# ──────────────────────── Shopify Integration ──────────────────────────


@router.post("/{site_id}/shopify/connect")
async def shopify_connect(
    site_id: str,
    body: ShopifyConnectRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Start Shopify OAuth flow to install pixel automatically."""
    if not settings.shopify_api_key:
        raise HTTPException(
            status_code=501,
            detail="Shopify integration not configured. Please set SHOPIFY_API_KEY.",
        )

    result = await db.execute(
        select(Site).where(Site.site_id == site_id, Site.user_id == user.id)
    )
    site = result.scalar_one_or_none()
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")

    from apps.api.services.shopify_integration import get_install_url

    install_url = get_install_url(body.shop_domain, site_id)
    return {"install_url": install_url}


@router.get("/shopify/callback")
async def shopify_callback(
    shop: str = Query(...),
    code: str = Query(...),
    state: str = Query(...),  # site_id
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    """Handle Shopify OAuth callback — install ScriptTag and redirect to dashboard."""
    site_id = state
    try:
        from apps.api.services.shopify_integration import handle_oauth_callback

        await handle_oauth_callback(shop, code, site_id)

        # Mark pixel as verified
        result = await db.execute(
            select(Site).where(Site.site_id == site_id)
        )
        site = result.scalar_one_or_none()
        if site:
            site.pixel_verified = True
            site.detected_platform = "shopify"
            await db.commit()

        logger.info("shopify_connected", shop=shop, site_id=site_id)
    except Exception as e:
        logger.error("shopify_callback_failed", error=str(e), shop=shop)

    return RedirectResponse(
        url=f"{settings.frontend_url}/dashboard?shopify=connected&site={site_id}"
    )
