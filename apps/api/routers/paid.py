"""Pay-per-call agent API (InFlow x402 seller) — /api/v1/paid/*.

Unauthenticated: the x402 payment IS the credential. Every route is wrapped by
``run_paid`` (verify -> handler -> settle; replay => cached response). Mounted
only when ``settings.inflow_x402_enabled`` (main.py); the per-request flag check
below is a second gate so a runtime flip-off answers 404 too.

Handlers here MUST be read-only — no user-visible state — because settlement
happens after the handler runs (see services/x402_seller.py).

Deliberately absent: identify-by-email (PII; pending legal review).
"""

import re

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from apps.api.config import settings
from apps.api.routers.demo import DraftRequest, fetch_social_posts, generate_draft_text
from apps.api.services.identity_providers.base import ProviderUnavailableError
from apps.api.services.identity_providers.pdl import enrich_company_by_domain
from apps.api.services.platform_detector import detect_platform
from apps.api.services.rate_limiter import limiter
from apps.api.services.x402_seller import PaymentHandlerError, run_paid

logger = structlog.get_logger()


def _require_enabled() -> None:
    if not settings.inflow_x402_enabled:
        raise HTTPException(status_code=404, detail="Not Found")


router = APIRouter(tags=["paid"], dependencies=[Depends(_require_enabled)])


# ─── Schemas ────────────────────────────────────────────────────────────────

_DOMAIN_RE = re.compile(r"^(?=.{1,253}$)(?!-)[a-z0-9-]{1,63}(?<!-)(\.(?!-)[a-z0-9-]{1,63}(?<!-))+$")


class CompanyFromDomainBody(BaseModel):
    domain: str = Field(..., max_length=300, description="Company website domain, e.g. stripe.com")


class SocialPostsBody(BaseModel):
    twitter_handle: str = Field(..., max_length=50)


class GenerateDraftBody(BaseModel):
    visitor_name: str = Field("", max_length=200)
    visitor_role: str = Field("", max_length=200)
    visitor_company: str = Field("", max_length=200)
    user_url: str = Field("", max_length=300)
    recent_post: str = Field("", max_length=2000)


class DetectPlatformBody(BaseModel):
    url: str = Field(..., max_length=2048)


def _normalize_domain(raw: str) -> str:
    d = raw.strip().lower()
    d = re.sub(r"^https?://", "", d).split("/")[0].split("?")[0].split(":")[0]
    if d.startswith("www."):
        d = d[4:]
    if not _DOMAIN_RE.match(d):
        # Validation happens BEFORE payment is verified, so a bad input never costs.
        raise HTTPException(status_code=422, detail="Invalid domain")
    return d


# ─── Routes ─────────────────────────────────────────────────────────────────


@router.post("/company-from-domain")
@limiter.limit("30/minute")
async def paid_company_from_domain(request: Request, body: CompanyFromDomainBody) -> Response:
    """Company firmographics for a website domain (PDL company enrich). $0.05."""
    domain = _normalize_domain(body.domain)

    async def handler() -> dict:
        try:
            company = await enrich_company_by_domain(domain)
        except ProviderUnavailableError as exc:
            raise PaymentHandlerError(503, "Company data provider unavailable") from exc
        return {"matched": company is not None, "company": company}

    return await run_paid(request, "company-from-domain", handler)


@router.post("/social-posts")
@limiter.limit("30/minute")
async def paid_social_posts(request: Request, body: SocialPostsBody) -> Response:
    """Recent public posts for an X/Twitter handle. $0.03."""
    handle = body.twitter_handle.lstrip("@").strip()
    if not re.fullmatch(r"[A-Za-z0-9_]{1,15}", handle):
        raise HTTPException(status_code=422, detail="Invalid handle")

    async def handler() -> dict:
        return await fetch_social_posts(handle)

    return await run_paid(request, "social-posts", handler)


@router.post("/generate-draft")
@limiter.limit("30/minute")
async def paid_generate_draft(request: Request, body: GenerateDraftBody) -> Response:
    """Short, casual social reply/engagement draft. $0.03."""
    draft_body = DraftRequest(**body.model_dump())

    async def handler() -> dict:
        return await generate_draft_text(draft_body)

    return await run_paid(request, "generate-draft", handler)


@router.post("/detect-platform")
@limiter.limit("60/minute")
async def paid_detect_platform(request: Request, body: DetectPlatformBody) -> Response:
    """Website platform detection (Shopify/WordPress/Webflow/...). $0.01."""

    async def handler() -> dict:
        try:
            r = await detect_platform(body.url)
        except Exception as exc:  # noqa: BLE001 — unreachable/refused site: do not charge
            logger.info("paid_detect_platform_failed", error_type=type(exc).__name__)
            raise PaymentHandlerError(502, "Could not analyze that URL") from exc
        return {
            "platform": r["platform"],
            "confidence": r["confidence"],
            "has_gtm": r["has_gtm"],
            "gtm_id": r["gtm_id"],
        }

    return await run_paid(request, "detect-platform", handler)
