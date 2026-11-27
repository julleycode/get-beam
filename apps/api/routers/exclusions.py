"""Per-site company/domain exclusion list (customers, competitors, other).

CRUD + CSV import. Enforcement lives in services/company_exclusion.py and is
gated by ``settings.company_exclusion_enabled``. Logs carry counts only.
"""

import uuid

import structlog
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.dependencies import get_current_user, verify_site_access
from apps.api.models.database import get_db
from apps.api.models.site_exclusion import SiteExclusion
from apps.api.models.user import User
from apps.api.schemas.exclusions import (
    ExclusionCreate,
    ExclusionImportError,
    ExclusionImportResult,
    ExclusionOut,
)
from apps.api.services.company_exclusion import (
    MAX_IMPORT_BYTES,
    parse_exclusions_csv,
    validate_exclusion_domain,
)

logger = structlog.get_logger()
router = APIRouter()


def _upsert_stmt(site_id: str, rows: list[dict]):
    stmt = pg_insert(SiteExclusion).values(
        [{"id": uuid.uuid4(), "site_id": site_id, **r} for r in rows]
    )
    return stmt.on_conflict_do_update(
        index_elements=["site_id", "domain"],
        set_={
            "company_name": stmt.excluded.company_name,
            "reason": stmt.excluded.reason,
            "note": stmt.excluded.note,
            "updated_at": func.now(),
        },
    )


@router.get("/{site_id}/exclusions", response_model=list[ExclusionOut])
async def list_exclusions(
    site_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[ExclusionOut]:
    await verify_site_access(db, site_id, user)
    rows = (
        await db.execute(
            select(SiteExclusion)
            .where(SiteExclusion.site_id == site_id)
            .order_by(SiteExclusion.domain)
        )
    ).scalars().all()
    return [ExclusionOut.model_validate(r) for r in rows]


@router.post("/{site_id}/exclusions", response_model=ExclusionOut, status_code=201)
async def create_exclusion(
    site_id: str,
    body: ExclusionCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ExclusionOut:
    await verify_site_access(db, site_id, user)
    domain, err = validate_exclusion_domain(body.domain)
    if err:
        raise HTTPException(status_code=422, detail=err)
    row = {
        "domain": domain,
        "company_name": body.company_name,
        "reason": body.reason,
        "note": body.note,
    }
    await db.execute(_upsert_stmt(site_id, [row]))
    await db.commit()
    saved = (
        await db.execute(
            select(SiteExclusion).where(
                SiteExclusion.site_id == site_id, SiteExclusion.domain == domain
            )
        )
    ).scalar_one()
    logger.info("company_exclusion_saved", site_id=site_id, count=1)
    return ExclusionOut.model_validate(saved)


@router.delete("/{site_id}/exclusions/{exclusion_id}", status_code=204)
async def delete_exclusion(
    site_id: str,
    exclusion_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    await verify_site_access(db, site_id, user)
    res = await db.execute(
        delete(SiteExclusion).where(
            SiteExclusion.site_id == site_id, SiteExclusion.id == exclusion_id
        )
    )
    if not res.rowcount:
        raise HTTPException(status_code=404, detail="Exclusion not found")
    await db.commit()
    logger.info("company_exclusion_deleted", site_id=site_id, count=1)


@router.post("/{site_id}/exclusions/import", response_model=ExclusionImportResult)
async def import_exclusions(
    site_id: str,
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ExclusionImportResult:
    """CSV ``domain,company_name,reason[,note]``; max 1 MB / 5000 rows.
    Valid rows are upserted on (site_id, domain); invalid rows are reported."""
    await verify_site_access(db, site_id, user)
    raw = await file.read(MAX_IMPORT_BYTES + 1)
    if len(raw) > MAX_IMPORT_BYTES:
        raise HTTPException(status_code=413, detail="File too large (max 1 MB)")
    valid, errors = parse_exclusions_csv(raw)
    if valid:
        await db.execute(_upsert_stmt(site_id, valid))
        await db.commit()
    logger.info(
        "company_exclusion_imported",
        site_id=site_id,
        upserted=len(valid),
        error_count=len(errors),
    )
    return ExclusionImportResult(
        upserted=len(valid), errors=[ExclusionImportError(**e) for e in errors]
    )
