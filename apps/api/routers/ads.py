"""Ad-audience connectors router — connect, test, and push segments OUT to an
ad platform's custom-audience surface.

REST surface (all under /api/v1/ads), scoped to a site owned by the caller,
except the OAuth callback which is validated by the OAuth state token instead.
Mirrors routers/crm.py route-for-route; routers/crm.py itself is untouched.

Status-code conventions (both are existing repo precedents, used concurrently
in routers/crm.py):
  * 404 — unknown provider, unknown/foreign site, missing connection
          (never 403: we don't leak which ids exist)
  * 400 — a real provider that structurally does not support this action
  * 501 — the route is reachable but the feature is unavailable server-side
          (feature flag off, credentials unconfigured, provider stub)
"""

import uuid
from urllib.parse import urlencode

import structlog
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.config import settings
from apps.api.dependencies import get_current_user, verify_site_access as _owned_site
from apps.api.models.ad_audience_link import AdAudienceLink
from apps.api.models.ad_connection import AdConnection
from apps.api.models.database import get_db
from apps.api.models.segment import Segment
from apps.api.models.user import User
from apps.api.schemas.ads import (
    ALLOWED_AD_PROVIDERS,
    AdConnectionOut,
    AdConnectResponse,
    AdTestResult,
    ClosedWonCsvResult,
    ClosedWonCsvUpload,
    ClosedWonLookalikeRequest,
    ClosedWonLookalikeResult,
    ClosedWonSeedSummary,
    PushAdSegmentRequest,
    PushAdSegmentResult,
)
from apps.api.services.ads.factory import get_provider, is_ready
from apps.api.services.ads.linkedin import build_linkedin_seed_csv
from apps.api.services.ads_push import build_hashed_contacts, get_connection, push_segment_to_ads
from apps.api.services.closed_won_seed import (
    SEED_SEGMENT_ID,
    LookalikeSpecError,
    SeedNotReadyError,
    build_seed,
    create_or_reuse_lookalike,
    ingest_deals,
    parse_closed_won_csv,
    push_seed,
    seed_summary,
    validate_spec,
)
from apps.api.services.ads_rate_limiter import check_and_reserve_push
from apps.api.services.encryption import encrypt_token
from apps.api.services.oauth_state import store_oauth_state, validate_oauth_state

logger = structlog.get_logger()

router = APIRouter()

# OAuth providers need their app credentials configured to start a flow.
_OAUTH_CREDENTIALS = {
    "meta": ("meta_ads_client_id", "meta_ads_client_secret"),
    "google": ("google_ads_client_id", "google_ads_client_secret"),
    "linkedin": ("linkedin_ads_client_id", "linkedin_ads_client_secret"),
}

_NOT_IMPLEMENTED_DETAIL = "Provider not yet implemented"


def _require_provider(provider: str) -> None:
    if provider not in ALLOWED_AD_PROVIDERS:
        raise HTTPException(status_code=404, detail="Unknown ad provider")


def _require_feature_enabled() -> None:
    """D6: one explicit status for the flag-off case — 501, matching the
    _OAUTH_CREDENTIALS-missing precedent in routers/crm.py (route reachable,
    feature structurally unavailable server-side)."""
    if not settings.ad_audiences_enabled:
        raise HTTPException(
            status_code=501,
            detail="Ad Audiences is not enabled for this deployment yet.",
        )


# ── List ─────────────────────────────────────────────────

@router.get("/{site_id}/connections", response_model=list[AdConnectionOut])
async def list_connections(
    site_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[AdConnectionOut]:
    await _owned_site(db, site_id, user)
    result = await db.execute(
        select(AdConnection).where(AdConnection.site_id == site_id)
    )
    return [AdConnectionOut.model_validate(c) for c in result.scalars().all()]


# ── OAuth: start ─────────────────────────────────────────

@router.post("/{site_id}/connections/{provider}/connect", response_model=AdConnectResponse)
async def connect_oauth(
    site_id: str,
    provider: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AdConnectResponse:
    _require_provider(provider)
    _require_feature_enabled()
    if not is_ready(provider):
        raise HTTPException(
            status_code=400, detail=f"{provider} audiences are not supported yet"
        )
    await _owned_site(db, site_id, user)

    required = _OAUTH_CREDENTIALS.get(provider, ())
    missing = [f for f in required if not getattr(settings, f, "")]
    if missing and not settings.mock_external_apis:
        raise HTTPException(
            status_code=501,
            detail=f"{provider} is not configured on the server yet.",
        )

    provider_impl = get_provider(provider)
    state = uuid.uuid4().hex
    # Pack site + provider into the state value (the store holds one string).
    await store_oauth_state(state, f"{user.id}:{site_id}:{provider}")
    try:
        auth_url = await provider_impl.get_oauth_url(state)
    except NotImplementedError:
        # D5: the stub providers raise until Phase 2/3 wires them. Surface a
        # clean 501 rather than an unhandled 500.
        raise HTTPException(status_code=501, detail=_NOT_IMPLEMENTED_DETAIL)
    return AdConnectResponse(auth_url=auth_url)


# ── OAuth: callback (no auth — validated by state) ───────

@router.get("/callback/{provider}")
async def oauth_callback(
    provider: str,
    code: str = "",
    state: str = "",
    error: str = "",
    db: AsyncSession = Depends(get_db),
):
    dest = f"{settings.frontend_url}/dashboard/connectors?tab=export"

    def redirect(**params) -> RedirectResponse:
        return RedirectResponse(f"{dest}&{urlencode(params)}")

    if provider not in ALLOWED_AD_PROVIDERS or not is_ready(provider):
        return redirect(ads="error", reason="unsupported_provider")
    if error or not code:
        return redirect(ads="error", reason=error or "no_code")

    packed = await validate_oauth_state(state)
    if not packed or packed.count(":") < 2:
        logger.warning("ads_oauth_state_invalid", provider=provider)
        return redirect(ads="error", reason="invalid_state")
    user_id_str, site_id, state_provider = packed.split(":", 2)
    if state_provider != provider:
        return redirect(ads="error", reason="provider_mismatch")

    provider_impl = get_provider(provider)
    try:
        tokens = await provider_impl.exchange_code(code, state=state)
    except NotImplementedError:
        return redirect(ads="error", reason="not_implemented")
    except Exception as exc:  # noqa: BLE001 — surface a generic failure, log detail
        logger.exception("ads_oauth_exchange_failed", provider=provider, error=str(exc))
        return redirect(ads="error", reason="exchange_failed")

    conn = await get_connection(db, site_id, provider)
    if conn is None:
        conn = AdConnection(
            id=uuid.uuid4(),
            site_id=site_id,
            user_id=uuid.UUID(user_id_str),
            provider=provider,
            auth_type="oauth",
        )
        db.add(conn)
    conn.access_token = encrypt_token(tokens.access_token)
    conn.refresh_token = encrypt_token(tokens.refresh_token) if tokens.refresh_token else None
    conn.token_expires_at = tokens.expires_at
    conn.scopes = tokens.scopes or None
    conn.external_account_id = tokens.external_account_id or None
    conn.external_account_label = tokens.external_account_label or provider
    conn.ad_account_id = tokens.ad_account_id or None
    conn.business_id = tokens.business_id or None
    conn.status = "connected"
    conn.is_valid = True
    conn.last_error = None
    await db.commit()
    logger.info("ads_oauth_connected", provider=provider, site_id=site_id)
    return redirect(ads="connected", provider=provider)


# ── Test ─────────────────────────────────────────────────

@router.post("/{site_id}/connections/{provider}/test", response_model=AdTestResult)
async def test_connection(
    site_id: str,
    provider: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AdTestResult:
    _require_provider(provider)
    _require_feature_enabled()
    await _owned_site(db, site_id, user)
    conn = await get_connection(db, site_id, provider)
    if conn is None:
        raise HTTPException(status_code=404, detail="Connection not found")

    provider_impl = get_provider(provider)
    try:
        outcome = await provider_impl.test_connection(conn)
    except NotImplementedError:
        raise HTTPException(status_code=501, detail=_NOT_IMPLEMENTED_DETAIL)

    conn.is_valid = outcome.is_valid
    conn.status = "connected" if outcome.is_valid else "error"
    await db.commit()
    return AdTestResult(
        provider=provider,
        is_valid=outcome.is_valid,
        message=outcome.message
        or ("Connection is live" if outcome.is_valid else "Connection test failed"),
    )


# ── Push a segment ───────────────────────────────────────

@router.post("/{site_id}/connections/{provider}/push", response_model=PushAdSegmentResult)
async def push_segment_endpoint(
    site_id: str,
    provider: str,
    body: PushAdSegmentRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PushAdSegmentResult:
    _require_provider(provider)
    _require_feature_enabled()
    await _owned_site(db, site_id, user)

    seg_result = await db.execute(
        select(Segment).where(Segment.id == body.segment_id, Segment.site_id == site_id)
    )
    if not seg_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Segment not found")

    conn = await get_connection(db, site_id, provider)
    if conn is None:
        raise HTTPException(status_code=404, detail="Connection not found")

    # Per-site hourly cap (reserve once here so the sync and async paths agree).
    if not await check_and_reserve_push(site_id):
        raise HTTPException(
            status_code=429,
            detail="Hourly ad push limit reached for this site. Try again later.",
        )

    try:
        outcome = await push_segment_to_ads(db, site_id, provider, body.segment_id)
    except NotImplementedError:
        raise HTTPException(status_code=501, detail=_NOT_IMPLEMENTED_DETAIL)

    return PushAdSegmentResult(
        provider=provider,
        segment_id=body.segment_id,
        pushed=outcome.pushed,
        failed=outcome.failed,
        skipped=outcome.skipped,
        platform_audience_id=outcome.platform_audience_id,
        warning=outcome.warning,
        below_minimum=outcome.below_minimum,
        minimum_threshold=outcome.minimum_threshold,
        errors=outcome.errors,
        queued=outcome.queued,
    )


# ── Disconnect ───────────────────────────────────────────

@router.delete("/{site_id}/connections/{provider}")
async def disconnect(
    site_id: str,
    provider: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    _require_provider(provider)
    _require_feature_enabled()
    await _owned_site(db, site_id, user)
    conn = await get_connection(db, site_id, provider)
    if conn is None:
        raise HTTPException(status_code=404, detail="Connection not found")
    conn.access_token = None
    conn.refresh_token = None
    conn.token_expires_at = None
    conn.status = "disconnected"
    conn.is_valid = False
    await db.commit()
    return {"status": "disconnected", "provider": provider}


# ── closed-won-lookalikes ────────────────────────────────
# UD4: closed-won flag OFF -> 404 (route does not exist); ad_audiences OFF ->
# the existing 501 for anything that talks to an ad platform.


def _require_closed_won_enabled() -> None:
    if not settings.closed_won_lookalikes_enabled:
        raise HTTPException(status_code=404, detail="Not found")


@router.post("/{site_id}/closed-won/csv", response_model=ClosedWonCsvResult)
async def upload_closed_won_csv(
    site_id: str,
    body: ClosedWonCsvUpload,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ClosedWonCsvResult:
    _require_closed_won_enabled()
    await _owned_site(db, site_id, user)
    try:
        deals = parse_closed_won_csv(body.csv)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    outcome = await ingest_deals(db, site_id, deals, source="csv")
    return ClosedWonCsvResult(
        upserted=outcome.upserted,
        skipped_erased=outcome.skipped_erased,
        skipped_invalid=outcome.skipped_invalid,
    )


@router.get("/{site_id}/closed-won/seed", response_model=ClosedWonSeedSummary)
async def get_closed_won_seed(
    site_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ClosedWonSeedSummary:
    _require_closed_won_enabled()
    await _owned_site(db, site_id, user)
    return ClosedWonSeedSummary(**(await seed_summary(db, site_id)))


@router.get("/{site_id}/closed-won/linkedin.csv")
async def export_closed_won_linkedin_csv(
    site_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """LinkedIn stays CSV-only: hashed seed for manual Matched Audiences upload."""
    _require_closed_won_enabled()
    await _owned_site(db, site_id, user)
    build = await build_seed(db, site_id)
    contacts = build_hashed_contacts([{"email": r.email} for r in build.rows])
    return Response(
        content=build_linkedin_seed_csv(contacts),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="closed-won-seed-linkedin.csv"'},
    )


@router.post("/{site_id}/closed-won/lookalike", response_model=ClosedWonLookalikeResult)
async def create_closed_won_lookalike(
    site_id: str,
    body: ClosedWonLookalikeRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ClosedWonLookalikeResult:
    _require_closed_won_enabled()
    _require_provider(body.provider)
    _require_feature_enabled()
    await _owned_site(db, site_id, user)
    try:
        spec, segment_key = validate_spec(body.provider, body.country, body.ratio, body.expansion)
    except LookalikeSpecError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    conn = await get_connection(db, site_id, body.provider)
    if conn is None:
        raise HTTPException(status_code=404, detail="Connection not found")

    seed_link = (
        await db.execute(
            select(AdAudienceLink).where(
                AdAudienceLink.connection_id == conn.id,
                AdAudienceLink.segment_id == SEED_SEGMENT_ID,
            )
        )
    ).scalar_one_or_none()
    seed_pushed: int | None = None
    seed_warning = ""
    if seed_link is None or body.push_seed:
        if not await check_and_reserve_push(site_id):
            raise HTTPException(
                status_code=429,
                detail="Hourly ad push limit reached for this site. Try again later.",
            )
        try:
            seed = await push_seed(db, site_id, body.provider)
        except NotImplementedError:
            raise HTTPException(status_code=501, detail=_NOT_IMPLEMENTED_DETAIL)
        if seed.errors and not seed.platform_audience_id:
            return ClosedWonLookalikeResult(provider=body.provider, error="; ".join(seed.errors))
        seed_pushed = seed.pushed
        seed_warning = seed.warning

    try:
        outcome = await create_or_reuse_lookalike(db, site_id, body.provider, spec, segment_key)
    except SeedNotReadyError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except NotImplementedError:
        raise HTTPException(status_code=501, detail=_NOT_IMPLEMENTED_DETAIL)

    seed_link = (
        await db.execute(
            select(AdAudienceLink).where(
                AdAudienceLink.connection_id == conn.id,
                AdAudienceLink.segment_id == SEED_SEGMENT_ID,
            )
        )
    ).scalar_one_or_none()
    return ClosedWonLookalikeResult(
        provider=body.provider,
        seed_audience_id=seed_link.platform_audience_id if seed_link else "",
        seed_pushed=seed_pushed,
        lookalike_audience_id=outcome.audience_id,
        status=outcome.status,
        reused=outcome.reused,
        previous_lookalike_id=outcome.previous_lookalike_id,
        warning=" ".join(w for w in (seed_warning, outcome.warning) if w),
        error=outcome.error,
    )
