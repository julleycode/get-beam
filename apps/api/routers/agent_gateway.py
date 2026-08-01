"""Public agent-facing read surface (agent-gateway Phase 2).

Unauthenticated, read-only, cacheable. Three routes, all per-site:

    GET /api/v1/agent/{site_id}/manifest.json
    GET /api/v1/agent/{site_id}/offers.json
    GET /api/v1/agent/{site_id}/llms.txt

Every route is doubly gated — ``settings.agent_gateway_enabled`` (global) AND
``AgentProfile.enabled`` (per-site). Either off => 404, endpoint not revealed
(same dormant posture as ``agent_fetch_beacon_enabled``). Unknown or foreign
site_id => 404 as well, NEVER 403: the response must not tell a caller whether
a site_id exists. All five failure modes funnel through
``resolve_public_profile`` and produce one identical 404, by construction.

The only write is the agent-visit bookkeeping in ``record_gateway_visit``, which
touches the two agent-only tables and nothing else — without it a recognized
agent could read this whole surface without ever appearing on the Agents
dashboard. Nothing here reads visitor, identity, or PII data — only the
customer-authored ``AgentProfile`` plus the site's own public name/url.

Phase 3 extends THIS file with the action endpoint. It is not present yet.
"""

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import PlainTextResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.config import settings
from apps.api.models.database import get_db
from apps.api.services.agent_gateway import (
    AGENT_CACHE_CONTROL,
    AGENT_OFFERS_MARKED_CACHE_CONTROL,
    SURFACE_LLMS_TXT,
    SURFACE_MANIFEST,
    SURFACE_OFFERS,
    build_llms_txt,
    build_manifest,
    build_offers,
    record_gateway_visit,
    resolve_public_profile,
)
from apps.api.services.agent_marker import mint_marker, stamp_marker
from apps.api.services.rate_limiter import limiter

router = APIRouter()
logger = structlog.get_logger()

# Matches the read-endpoint budget used by the other public routes in this repo
# (see routers/demo.py). Generous enough for a legitimate agent that polls a
# manifest, tight enough to make scraping every site_id expensive.
PUBLIC_READ_LIMIT = "60/minute"

_NOT_FOUND = HTTPException(status_code=404, detail="Not found")


async def _profile_or_404(db: AsyncSession, site_id: str):
    resolved = await resolve_public_profile(db, site_id)
    if resolved is None:
        # Single shared 404 for: flag off / unknown site / no profile /
        # profile disabled. Deliberately indistinguishable — never 403.
        raise _NOT_FOUND
    return resolved


@router.get("/{site_id}/manifest.json")
@limiter.limit(PUBLIC_READ_LIMIT)
async def get_manifest(
    request: Request,
    site_id: str,
    db: AsyncSession = Depends(get_db),
) -> Response:
    site, profile = await _profile_or_404(db, site_id)
    await record_gateway_visit(db, request, site_id, SURFACE_MANIFEST)
    manifest = build_manifest(site, profile)
    return Response(
        content=manifest.model_dump_json(),
        media_type="application/json",
        headers={"Cache-Control": AGENT_CACHE_CONTROL},
    )


@router.get("/{site_id}/offers.json")
@limiter.limit(PUBLIC_READ_LIMIT)
async def get_offers(
    request: Request,
    site_id: str,
    db: AsyncSession = Depends(get_db),
) -> Response:
    site, profile = await _profile_or_404(db, site_id)
    fetch_event_id = await record_gateway_visit(db, request, site_id, SURFACE_OFFERS)
    feed = build_offers(site, profile)

    # F2: tie the links this agent is about to surface back to THIS fetch, so a
    # human clicking one is matched deterministically instead of guessed at by
    # the 30-minute temporal sweep. The whole surface drops to no-store while the
    # flag is on, not just the marked responses: a mixed posture would leave a
    # shared cache holding an unmarked body and silently losing attribution for
    # every agent behind it, for a caching win worth nothing at this volume.
    cache_control = AGENT_CACHE_CONTROL
    if settings.agent_marker_enabled:
        cache_control = AGENT_OFFERS_MARKED_CACHE_CONTROL
        marker = mint_marker(fetch_event_id)
        if marker:
            for offer in feed.offers:
                offer.url = stamp_marker(offer.url, marker, site.url)
        # The mint-side half of the F2 audit trail. Paired with agent_marker_seen
        # on the click side, this is what separates "no agent ever fetched the
        # feed" from "markers went out but none came back" — the second being the
        # signal that an AI surface stripped the query parameter, which cannot be
        # determined from the code. has_fetch distinguishes an unrecognized agent
        # (no row to name) from a minting failure (no encryption key). Keys only.
        logger.info(
            "agent_marker_minted",
            site_id=site_id,
            has_fetch=fetch_event_id is not None,
            minted=marker is not None,
            offers=len(feed.offers),
        )

    return Response(
        content=feed.model_dump_json(),
        media_type="application/json",
        headers={"Cache-Control": cache_control},
    )


@router.get("/{site_id}/llms.txt", response_class=PlainTextResponse)
@limiter.limit(PUBLIC_READ_LIMIT)
async def get_llms_txt(
    request: Request,
    site_id: str,
    db: AsyncSession = Depends(get_db),
) -> Response:
    site, profile = await _profile_or_404(db, site_id)
    await record_gateway_visit(db, request, site_id, SURFACE_LLMS_TXT)
    return PlainTextResponse(
        content=build_llms_txt(site, profile),
        headers={"Cache-Control": AGENT_CACHE_CONTROL},
    )
