"""Changelog — public read (published only) + admin CRUD/publish.

Backend for the "what's new" pill on getbeam.fyi. Public endpoints are
unauthenticated and only expose published entries. Write + draft access
requires admin. Mirrors routers/blog.py, minus slug/SEO/scheduling.
"""

import uuid
from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.dependencies import require_admin
from apps.api.models.changelog_entry import ChangelogEntry
from apps.api.models.database import get_db
from apps.api.models.user import User
from apps.api.schemas.changelog import (
    ChangelogAdminListResponse,
    ChangelogEntryAdminOut,
    ChangelogEntryCreate,
    ChangelogEntryOut,
    ChangelogEntryUpdate,
    ChangelogListResponse,
    ChangelogSyncResponse,
)
from apps.api.services import changelog_generator

logger = structlog.get_logger()

router = APIRouter(tags=["changelog"])


# ── Public ─────────────────────────────────────────────────────────────


@router.get("/entries", response_model=ChangelogListResponse)
async def list_published_entries(
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=10, ge=1, le=50),
    offset: int = Query(default=0, ge=0),
) -> ChangelogListResponse:
    """Published entries, newest first."""
    cond = ChangelogEntry.status == "published"
    total = (
        await db.execute(select(func.count()).select_from(ChangelogEntry).where(cond))
    ).scalar_one()
    rows = (
        await db.execute(
            select(ChangelogEntry)
            .where(cond)
            .order_by(desc(ChangelogEntry.published_at))
            .limit(limit)
            .offset(offset)
        )
    ).scalars().all()
    return ChangelogListResponse(
        entries=[ChangelogEntryOut.model_validate(e) for e in rows], total=total
    )


# ── Admin ──────────────────────────────────────────────────────────────


@router.get("/admin/entries", response_model=ChangelogAdminListResponse)
async def list_all_entries(
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> ChangelogAdminListResponse:
    """All entries (any status), newest first. Admin only."""
    total = (
        await db.execute(select(func.count()).select_from(ChangelogEntry))
    ).scalar_one()
    rows = (
        await db.execute(
            select(ChangelogEntry)
            .order_by(desc(ChangelogEntry.created_at))
            .limit(limit)
            .offset(offset)
        )
    ).scalars().all()
    return ChangelogAdminListResponse(
        entries=[ChangelogEntryAdminOut.model_validate(e) for e in rows], total=total
    )


@router.post(
    "/entries", response_model=ChangelogEntryAdminOut, status_code=status.HTTP_201_CREATED
)
async def create_entry(
    payload: ChangelogEntryCreate,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> ChangelogEntryAdminOut:
    """Create a new draft entry."""
    entry = ChangelogEntry(
        title=payload.title,
        body=payload.body or "",
        category=payload.category,
        status="draft",
    )
    db.add(entry)
    await db.commit()
    await db.refresh(entry)
    logger.info("changelog_entry_created", entry_id=str(entry.id))
    return ChangelogEntryAdminOut.model_validate(entry)


@router.post("/sync", response_model=ChangelogSyncResponse)
async def sync_from_github(
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
    limit: int = Query(default=30, ge=1, le=100),
) -> ChangelogSyncResponse:
    """Pull recent merged PRs and auto-publish the customer-facing ones.

    Idempotent — PRs already imported are skipped. Internal work (refactors,
    chores) is dropped by the Gemini classify step.
    """
    try:
        return await changelog_generator.sync_from_github(db, limit=limit)
    except changelog_generator.ChangelogSyncError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        )


async def _get_or_404(db: AsyncSession, entry_id: uuid.UUID) -> ChangelogEntry:
    entry = (
        await db.execute(select(ChangelogEntry).where(ChangelogEntry.id == entry_id))
    ).scalar_one_or_none()
    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Entry not found"
        )
    return entry


@router.put("/entries/{entry_id}", response_model=ChangelogEntryAdminOut)
async def update_entry(
    entry_id: uuid.UUID,
    payload: ChangelogEntryUpdate,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> ChangelogEntryAdminOut:
    """Partial update."""
    entry = await _get_or_404(db, entry_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(entry, field, value)
    await db.commit()
    await db.refresh(entry)
    logger.info("changelog_entry_updated", entry_id=str(entry.id))
    return ChangelogEntryAdminOut.model_validate(entry)


@router.post("/entries/{entry_id}/publish", response_model=ChangelogEntryAdminOut)
async def publish_entry(
    entry_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> ChangelogEntryAdminOut:
    """Set status=published. Stamp published_at only on first publish."""
    entry = await _get_or_404(db, entry_id)
    entry.status = "published"
    if entry.published_at is None:
        entry.published_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(entry)
    logger.info("changelog_entry_published", entry_id=str(entry.id))
    return ChangelogEntryAdminOut.model_validate(entry)


@router.post("/entries/{entry_id}/unpublish", response_model=ChangelogEntryAdminOut)
async def unpublish_entry(
    entry_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> ChangelogEntryAdminOut:
    """Revert to draft. Keeps published_at for audit history."""
    entry = await _get_or_404(db, entry_id)
    entry.status = "draft"
    await db.commit()
    await db.refresh(entry)
    logger.info("changelog_entry_unpublished", entry_id=str(entry.id))
    return ChangelogEntryAdminOut.model_validate(entry)


@router.delete("/entries/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_entry(
    entry_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> None:
    """Hard delete an entry."""
    entry = await _get_or_404(db, entry_id)
    await db.delete(entry)
    await db.commit()
    logger.info("changelog_entry_deleted", entry_id=str(entry_id))
