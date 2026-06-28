"""CRM connectors router — connect, test, and push identified visitors OUT.

REST surface (all under /api/v1/crm), scoped to a site owned by the caller,
except the OAuth callback which is validated by the OAuth state token instead.
"""

import uuid
from urllib.parse import urlencode

import structlog
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.config import settings
from apps.api.dependencies import get_current_user
from apps.api.models.crm_connection import CrmConnection
from apps.api.models.database import get_db
from apps.api.models.segment import Segment, SegmentMember
from apps.api.models.site import Site
from apps.api.models.user import User
from apps.api.schemas.crm import (
    ALLOWED_CRM_PROVIDERS,
    OAUTH_CRM_PROVIDERS,
    CrmConnectResponse,
    CrmConnectionOut,
    CrmTestResult,
    FieldMappingUpdate,
    GenericWebhookCreate,
    PushSegmentRequest,
    PushSegmentResult,
)
from apps.api.services.crm import get_crm_connector
from apps.api.services.crm_push import fresh_access_token, get_connection, push_segment
from apps.api.services.crm_rate_limiter import check_and_reserve_push
from apps.api.services.encryption import encrypt_token
from apps.api.services.key_vault import decrypt_key, encrypt_key, make_key_hint
from apps.api.services.oauth_state import store_oauth_state, validate_oauth_state
from apps.api.services.url_guard import is_safe_public_url

logger = structlog.get_logger()

router = APIRouter()

# OAuth providers need their app credentials configured to start a flow.
_OAUTH_CREDENTIALS = {
    "hubspot": ("hubspot_client_id", "hubspot_client_secret"),
    "pipedrive": ("pipedrive_client_id", "pipedrive_client_secret"),
    "salesforce": ("salesforce_client_id", "salesforce_client_secret"),
}


def _require_provider(provider: str) -> None:
    if provider not in ALLOWED_CRM_PROVIDERS:
        raise HTTPException(status_code=404, detail="Unknown CRM provider")


async def _owned_site(db: AsyncSession, site_id: str, user: User) -> Site:
    result = await db.execute(
        select(Site).where(Site.site_id == site_id, Site.user_id == user.id)
    )
    site = result.scalar_one_or_none()
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")
    return site


# Connection lookup + token refresh live in services/crm_push (shared with the
# Celery task and the auto-push hook) and are imported above.


# ── List ─────────────────────────────────────────────────

@router.get("/{site_id}/connections", response_model=list[CrmConnectionOut])
async def list_connections(
    site_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[CrmConnectionOut]:
    await _owned_site(db, site_id, user)
    result = await db.execute(
        select(CrmConnection).where(CrmConnection.site_id == site_id)
    )
    return [CrmConnectionOut.model_validate(c) for c in result.scalars().all()]


# ── Generic webhook: save / replace ──────────────────────

@router.put("/{site_id}/connections/generic_webhook", response_model=CrmConnectionOut)
async def save_generic_webhook(
    site_id: str,
    body: GenericWebhookCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CrmConnectionOut:
    await _owned_site(db, site_id, user)

    webhook_url = str(body.webhook_url)
    # SSRF guard: reject private / loopback / link-local / metadata hosts.
    if not await is_safe_public_url(webhook_url):
        raise HTTPException(
            status_code=400,
            detail="Webhook URL must be a public http(s) address (private/loopback hosts are not allowed).",
        )

    connector = get_crm_connector("generic_webhook")
    is_valid = await connector.test_connection(webhook_url=webhook_url, secret=body.secret)

    conn = await get_connection(db, site_id, "generic_webhook")
    if conn is None:
        conn = CrmConnection(
            id=uuid.uuid4(),
            site_id=site_id,
            user_id=user.id,
            provider="generic_webhook",
            auth_type="webhook",
        )
        db.add(conn)
    conn.webhook_url = webhook_url
    conn.encrypted_secret = encrypt_key(body.secret)
    conn.secret_hint = make_key_hint(body.secret)
    conn.is_valid = is_valid
    conn.status = "connected" if is_valid else "error"
    conn.last_error = None if is_valid else "Webhook test ping failed"
    await db.commit()
    await db.refresh(conn)
    logger.info("crm_webhook_saved", site_id=site_id, is_valid=is_valid)
    return CrmConnectionOut.model_validate(conn)


# ── OAuth: start ─────────────────────────────────────────

@router.post("/{site_id}/connections/{provider}/connect", response_model=CrmConnectResponse)
async def connect_oauth(
    site_id: str,
    provider: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CrmConnectResponse:
    _require_provider(provider)
    if provider not in OAUTH_CRM_PROVIDERS:
        raise HTTPException(status_code=400, detail=f"{provider} does not use OAuth")
    await _owned_site(db, site_id, user)

    required = _OAUTH_CREDENTIALS.get(provider, ())
    missing = [f for f in required if not getattr(settings, f, "")]
    if missing:
        raise HTTPException(
            status_code=501,
            detail=f"{provider} is not configured on the server yet.",
        )

    connector = get_crm_connector(provider)
    state = uuid.uuid4().hex
    # Pack site + provider into the state value (the store holds one string).
    await store_oauth_state(state, f"{user.id}:{site_id}:{provider}")
    auth_url = await connector.get_auth_url(state)
    return CrmConnectResponse(auth_url=auth_url)


# ── OAuth: callback (no auth — validated by state) ───────

@router.get("/callback/{provider}")
async def oauth_callback(
    provider: str,
    code: str = "",
    state: str = "",
    error: str = "",
    db: AsyncSession = Depends(get_db),
):
    dest = f"{settings.frontend_url}/dashboard/connectors?tab=connect"

    def redirect(**params) -> RedirectResponse:
        return RedirectResponse(f"{dest}&{urlencode(params)}")

    if provider not in OAUTH_CRM_PROVIDERS:
        return redirect(crm="error", reason="unsupported_provider")
    if error or not code:
        return redirect(crm="error", reason=error or "no_code")

    packed = await validate_oauth_state(state)
    if not packed or packed.count(":") < 2:
        logger.warning("crm_oauth_state_invalid", provider=provider)
        return redirect(crm="error", reason="invalid_state")
    user_id_str, site_id, state_provider = packed.split(":", 2)
    if state_provider != provider:
        return redirect(crm="error", reason="provider_mismatch")

    connector = get_crm_connector(provider)
    try:
        tokens = await connector.exchange_code(code, state=state)
    except Exception as exc:  # noqa: BLE001 — surface a generic failure, log detail
        logger.exception("crm_oauth_exchange_failed", provider=provider, error=str(exc))
        return redirect(crm="error", reason="exchange_failed")

    conn = await get_connection(db, site_id, provider)
    if conn is None:
        conn = CrmConnection(
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
    conn.status = "connected"
    conn.is_valid = True
    conn.last_error = None
    await db.commit()
    logger.info("crm_oauth_connected", provider=provider, site_id=site_id)
    return redirect(crm="connected", provider=provider)


# ── Test ─────────────────────────────────────────────────

@router.post("/{site_id}/connections/{provider}/test", response_model=CrmTestResult)
async def test_connection(
    site_id: str,
    provider: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CrmTestResult:
    _require_provider(provider)
    await _owned_site(db, site_id, user)
    conn = await get_connection(db, site_id, provider)
    if conn is None:
        raise HTTPException(status_code=404, detail="Connection not found")

    connector = get_crm_connector(provider)
    if conn.auth_type == "oauth":
        access_token = await fresh_access_token(db, conn)
        is_valid = await connector.test_connection(
            access_token=access_token, instance_url=conn.external_account_id or ""
        )
    else:
        secret = decrypt_key(conn.encrypted_secret) if conn.encrypted_secret else ""
        is_valid = await connector.test_connection(
            webhook_url=conn.webhook_url or "", secret=secret
        )

    conn.is_valid = is_valid
    conn.status = "connected" if is_valid else "error"
    await db.commit()
    return CrmTestResult(
        provider=provider,
        is_valid=is_valid,
        message="Connection is live" if is_valid else "Connection test failed",
    )


# ── Push a segment ───────────────────────────────────────

@router.post("/{site_id}/connections/{provider}/push", response_model=PushSegmentResult)
async def push_segment_endpoint(
    site_id: str,
    provider: str,
    body: PushSegmentRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PushSegmentResult:
    _require_provider(provider)
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
            status_code=429, detail="Hourly CRM push limit reached for this site. Try again later."
        )

    member_count = (
        await db.scalar(
            select(func.count())
            .select_from(SegmentMember)
            .where(SegmentMember.segment_id == body.segment_id)
        )
        or 0
    )

    # Offload big segments to a worker when enabled (and one is running).
    if settings.crm_async_push and member_count > settings.crm_async_push_threshold:
        from apps.api.tasks.crm_tasks import push_segment_to_crm

        push_segment_to_crm.delay(site_id, provider, body.segment_id)
        logger.info(
            "crm_push_queued", site_id=site_id, provider=provider, members=member_count
        )
        return PushSegmentResult(
            provider=provider,
            segment_id=body.segment_id,
            pushed=0,
            failed=0,
            skipped=0,
            queued=True,
        )

    outcome = await push_segment(db, site_id, provider, body.segment_id)
    return PushSegmentResult(
        provider=provider,
        segment_id=body.segment_id,
        pushed=outcome.pushed,
        failed=outcome.failed,
        skipped=outcome.skipped,
        errors=outcome.errors,
    )


# ── Field mapping ────────────────────────────────────────

@router.patch("/{site_id}/connections/{provider}", response_model=CrmConnectionOut)
async def update_field_mapping(
    site_id: str,
    provider: str,
    body: FieldMappingUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CrmConnectionOut:
    _require_provider(provider)
    await _owned_site(db, site_id, user)
    conn = await get_connection(db, site_id, provider)
    if conn is None:
        raise HTTPException(status_code=404, detail="Connection not found")
    conn.field_mapping = body.field_mapping
    await db.commit()
    await db.refresh(conn)
    return CrmConnectionOut.model_validate(conn)


# ── Disconnect ───────────────────────────────────────────

@router.delete("/{site_id}/connections/{provider}")
async def disconnect(
    site_id: str,
    provider: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    _require_provider(provider)
    await _owned_site(db, site_id, user)
    conn = await get_connection(db, site_id, provider)
    if conn is None:
        raise HTTPException(status_code=404, detail="Connection not found")
    await db.delete(conn)
    await db.commit()
    return {"status": "disconnected", "provider": provider}
