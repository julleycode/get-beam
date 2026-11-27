"""Ad conversion config + delivery log (conversion-apis_27-11-26).

All routes under /api/v1/ad-conversions, scoped to a site owned by the caller
(404 for unknown/foreign ids — never 403). Responses carry ids, statuses and
reason codes only — no PII.
"""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.dependencies import get_current_user, verify_site_access
from apps.api.models.ad_conversion import CONVERSION_PLATFORMS, AdConversionConfig, AdConversionDelivery
from apps.api.models.database import get_db
from apps.api.models.user import User

router = APIRouter()

_MAX_MAP_ENTRIES = 200


class ConversionConfigIn(BaseModel):
    goal_event_map: dict[str, str] = Field(default_factory=dict)
    meta_dataset_id: Optional[str] = Field(default=None, max_length=64)
    meta_test_event_code: Optional[str] = Field(default=None, max_length=64)
    google_operating_account_id: Optional[str] = Field(default=None, max_length=64)
    google_product_destination_id: Optional[str] = Field(default=None, max_length=64)
    validate_only: bool = True
    eea_consent_attested: bool = False


class ConversionConfigOut(ConversionConfigIn):
    model_config = ConfigDict(from_attributes=True)
    site_id: str
    platform: str
    goal_watermark_at: Optional[datetime] = None
    lead_watermark_at: Optional[datetime] = None


class DeliveryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    visitor_id: str
    platform: str
    conversion_type: str
    goal_id: Optional[str] = None
    dedup_id: str
    status: str
    attempts: int
    last_error: Optional[str] = None
    occurred_at: datetime
    sent_at: Optional[datetime] = None
    created_at: Optional[datetime] = None


class DeliveryPage(BaseModel):
    total: int
    items: list[DeliveryOut]


def _require_platform(platform: str) -> None:
    if platform not in CONVERSION_PLATFORMS:
        raise HTTPException(status_code=404, detail="Unknown platform")


def _validate_map(m: dict[str, str]) -> dict[str, str]:
    if len(m) > _MAX_MAP_ENTRIES:
        raise HTTPException(status_code=422, detail="Too many goal mappings")
    clean: dict[str, str] = {}
    for k, v in m.items():
        k, v = (k or "").strip(), (v or "").strip()
        if not k or not v or len(k) > 64 or len(v) > 100:
            raise HTTPException(status_code=422, detail="Invalid goal mapping")
        clean[k] = v
    return clean


async def _get_config(db: AsyncSession, site_id: str, platform: str) -> AdConversionConfig | None:
    return (
        await db.execute(
            select(AdConversionConfig).where(
                AdConversionConfig.site_id == site_id, AdConversionConfig.platform == platform
            )
        )
    ).scalar_one_or_none()


@router.get("/{site_id}/config/{platform}", response_model=ConversionConfigOut)
async def get_config(
    site_id: str,
    platform: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ConversionConfigOut:
    await verify_site_access(db, site_id, user)
    _require_platform(platform)
    cfg = await _get_config(db, site_id, platform)
    if cfg is None:
        return ConversionConfigOut(site_id=site_id, platform=platform)
    return ConversionConfigOut.model_validate(cfg)


@router.put("/{site_id}/config/{platform}", response_model=ConversionConfigOut)
async def put_config(
    site_id: str,
    platform: str,
    body: ConversionConfigIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ConversionConfigOut:
    await verify_site_access(db, site_id, user)
    _require_platform(platform)
    data = body.model_dump()
    data["goal_event_map"] = _validate_map(body.goal_event_map)
    cfg = await _get_config(db, site_id, platform)
    if cfg is None:
        cfg = AdConversionConfig(site_id=site_id, platform=platform, **data)
        db.add(cfg)
    else:
        for k, v in data.items():
            setattr(cfg, k, v)
    await db.commit()
    await db.refresh(cfg)
    return ConversionConfigOut.model_validate(cfg)


@router.get("/{site_id}/deliveries", response_model=DeliveryPage)
async def list_deliveries(
    site_id: str,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DeliveryPage:
    await verify_site_access(db, site_id, user)
    total = (
        await db.execute(
            select(func.count()).select_from(AdConversionDelivery).where(
                AdConversionDelivery.site_id == site_id
            )
        )
    ).scalar_one()
    rows = (
        await db.execute(
            select(AdConversionDelivery)
            .where(AdConversionDelivery.site_id == site_id)
            .order_by(AdConversionDelivery.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
    ).scalars().all()
    items = [
        DeliveryOut.model_validate({**{c: getattr(r, c) for c in DeliveryOut.model_fields}, "id": str(r.id)})
        for r in rows
    ]
    return DeliveryPage(total=total, items=items)


@router.get("/{site_id}/linkedin.csv")
async def linkedin_csv(
    site_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    await verify_site_access(db, site_id, user)
    from apps.api.services.ad_conversions import linkedin_export_events
    from apps.api.services.ads.linkedin import build_linkedin_conversions_csv

    events = await linkedin_export_events(db, site_id)
    return Response(
        content=build_linkedin_conversions_csv(events),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="linkedin-conversions.csv"'},
    )
