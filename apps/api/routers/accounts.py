"""Accounts router — per-company-domain rollup (account-measurement, gap #14).

Read-only and flag-gated: ``account_rollup_enabled`` OFF → 404 on both routes.
Foreign site and unknown domain → 404 (never leak id existence).
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.config import settings
from apps.api.dependencies import get_current_user, verify_site_access
from apps.api.models.database import get_db
from apps.api.models.user import User
from apps.api.schemas.account_rollup import (
    AccountDetail,
    AccountListParams,
    AccountListResponse,
)
from apps.api.services.account_rollup import get_account, list_accounts

router = APIRouter()


def _require_flag() -> None:
    if not settings.account_rollup_enabled:
        raise HTTPException(status_code=404, detail="Not found")


@router.get("/{site_id}", response_model=AccountListResponse)
async def list_site_accounts(
    site_id: str,
    params: AccountListParams = Depends(),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AccountListResponse:
    _require_flag()
    await verify_site_access(db, site_id, user)
    return await list_accounts(
        db, site_id, params.days, params.sort, params.page, params.page_size
    )


@router.get("/{site_id}/{domain}", response_model=AccountDetail)
async def get_site_account(
    site_id: str,
    domain: str,
    params: AccountListParams = Depends(),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AccountDetail:
    _require_flag()
    await verify_site_access(db, site_id, user)
    detail = await get_account(db, site_id, domain, params.days)
    if detail is None:
        raise HTTPException(status_code=404, detail="Account not found")
    return detail
