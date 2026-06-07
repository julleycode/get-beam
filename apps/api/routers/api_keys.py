"""BYOK API key management — users store their own Proxycurl/Twitter keys."""

import httpx
import structlog
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.config import settings
from apps.api.models.api_key import UserApiKey
from apps.api.models.database import get_db
from apps.api.models.user import User
from apps.api.dependencies import get_current_user
from apps.api.schemas.api_keys import (
    ALLOWED_PROVIDERS,
    ApiKeyCreate,
    ApiKeyOut,
    ApiKeyTestResult,
)
from apps.api.services.key_vault import decrypt_key, encrypt_key, make_key_hint

router = APIRouter()
logger = structlog.get_logger()


@router.get("/", response_model=list[ApiKeyOut])
async def list_api_keys(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[ApiKeyOut]:
    """List user's stored API keys (hints only, never the actual key)."""
    result = await db.execute(
        select(UserApiKey).where(UserApiKey.user_id == user.id)
    )
    return [ApiKeyOut.model_validate(k) for k in result.scalars().all()]


@router.post("/", response_model=ApiKeyOut)
async def save_api_key(
    body: ApiKeyCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiKeyOut:
    """Save (or replace) an API key. Validates with a test call first."""
    if body.provider not in ALLOWED_PROVIDERS:
        raise HTTPException(
            status_code=400,
            detail=f"Provider must be one of: {', '.join(sorted(ALLOWED_PROVIDERS))}",
        )

    # Validate the key with a test call
    is_valid = await _test_key(body.provider, body.api_key)

    # Upsert: delete existing key for this provider, then insert
    await db.execute(
        delete(UserApiKey).where(
            UserApiKey.user_id == user.id,
            UserApiKey.provider == body.provider,
        )
    )

    key_record = UserApiKey(
        user_id=user.id,
        provider=body.provider,
        encrypted_key=encrypt_key(body.api_key),
        key_hint=make_key_hint(body.api_key),
        is_valid=is_valid,
    )
    db.add(key_record)
    await db.commit()
    await db.refresh(key_record)

    logger.info("api_key_saved", provider=body.provider, is_valid=is_valid)
    return ApiKeyOut.model_validate(key_record)


@router.delete("/{provider}")
async def delete_api_key(
    provider: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Remove a stored API key."""
    result = await db.execute(
        delete(UserApiKey).where(
            UserApiKey.user_id == user.id,
            UserApiKey.provider == provider,
        )
    )
    if result.rowcount == 0:  # type: ignore[union-attr]
        raise HTTPException(status_code=404, detail="API key not found")
    await db.commit()
    return {"status": "deleted", "provider": provider}


@router.post("/{provider}/test", response_model=ApiKeyTestResult)
async def test_api_key(
    provider: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiKeyTestResult:
    """Test if a stored API key is still valid."""
    result = await db.execute(
        select(UserApiKey).where(
            UserApiKey.user_id == user.id,
            UserApiKey.provider == provider,
        )
    )
    key_record = result.scalar_one_or_none()
    if not key_record:
        raise HTTPException(status_code=404, detail="API key not found")

    plaintext = decrypt_key(key_record.encrypted_key)
    is_valid = await _test_key(provider, plaintext)

    key_record.is_valid = is_valid
    await db.commit()

    return ApiKeyTestResult(
        provider=provider,
        is_valid=is_valid,
        message="Key is valid" if is_valid else "Key validation failed",
    )


async def _test_key(provider: str, api_key: str) -> bool:
    """Make a lightweight test call to verify the API key works."""
    if settings.mock_external_apis:
        return True

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            if provider == "proxycurl":
                resp = await client.get(
                    "https://nubela.co/proxycurl/api/credit-balance",
                    headers={"Authorization": f"Bearer {api_key}"},
                )
                return resp.status_code == 200

            elif provider == "twitter":
                resp = await client.get(
                    "https://api.twitter.com/2/users/me",
                    headers={"Authorization": f"Bearer {api_key}"},
                )
                return resp.status_code in (200, 403)

            elif provider == "openrouter":
                resp = await client.get(
                    "https://openrouter.ai/api/v1/auth/key",
                    headers={"Authorization": f"Bearer {api_key}"},
                )
                return resp.status_code == 200

            elif provider == "anthropic":
                resp = await client.get(
                    "https://api.anthropic.com/v1/models",
                    headers={
                        "x-api-key": api_key,
                        "anthropic-version": "2023-06-01",
                    },
                )
                return resp.status_code == 200

            elif provider == "people_data_labs":
                resp = await client.get(
                    "https://api.peopledatalabs.com/v5/person/enrich",
                    headers={"X-Api-Key": api_key},
                    params={"email": "test@test.com"},
                )
                return resp.status_code in (200, 404)

            else:
                # Providers without test endpoints (rb2b, leadpipe, capturify,
                # customers_ai, hunter, apollo, facebook, linkedin, etc.)
                # — accept the key on trust, validate on first real use.
                return bool(api_key and len(api_key) >= 10)

    except httpx.HTTPError as e:
        logger.warning("api_key_test_failed", provider=provider, error=str(e))
    return False
