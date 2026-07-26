"""Authed CRUD for a site's agent-facing profile (agent-gateway Phase 1).

Every route is Clerk-session-gated and site-scoped through
``verify_site_access`` (``apps/api/dependencies.py:29``), which raises 404 —
never 403 — for an unknown or foreign ``site_id`` so we never leak which
site_ids exist. No public/unauthenticated surface is introduced here; the
public agent-facing reads live in ``routers/agent_gateway.py`` (Phase 2).

First-read behavior (plan instruction E7): ``GET`` returns 404 when no profile
row exists yet — a bare read never creates one. ``PUT`` upserts (creates on
first write, patches thereafter). This matches ordinary REST semantics and
avoids surprising empty-row creation from a read.
"""

import structlog
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.dependencies import get_current_user, verify_site_access
from apps.api.models.agent_profile import AgentProfile
from apps.api.models.database import get_db
from apps.api.models.user import User
from apps.api.schemas.agent_profile import AgentProfileOut, AgentProfileUpdate

router = APIRouter()
logger = structlog.get_logger()


async def _load_profile(db: AsyncSession, site_id: str) -> AgentProfile | None:
    return (
        await db.execute(
            select(AgentProfile).where(AgentProfile.site_id == site_id)
        )
    ).scalar_one_or_none()


@router.get("/{site_id}", response_model=AgentProfileOut)
async def get_agent_profile(
    site_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AgentProfile:
    """Read this site's agent profile. 404 if the site isn't yours, and 404 if
    no profile has been saved yet (see module docstring, E7)."""
    await verify_site_access(db, site_id, user)

    profile = await _load_profile(db, site_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Agent profile not found")
    return profile


@router.put("/{site_id}", response_model=AgentProfileOut)
async def upsert_agent_profile(
    site_id: str,
    body: AgentProfileUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AgentProfile:
    """Create-or-patch this site's agent profile. Only set fields are applied."""
    await verify_site_access(db, site_id, user)

    profile = await _load_profile(db, site_id)
    created = profile is None
    if profile is None:
        # Defaults set explicitly rather than left to the column defaults: a
        # public-exposure kill switch should be OFF by construction, not by
        # flush-time side effect. Body fields below can still turn it on.
        profile = AgentProfile(
            site_id=site_id, enabled=False, offers=[], capabilities=[]
        )
        db.add(profile)

    fields = body.model_dump(exclude_unset=True)
    if "offers" in fields and fields["offers"] is not None:
        fields["offers"] = [o.model_dump() for o in body.offers or []]

    for key, value in fields.items():
        if value is not None:
            setattr(profile, key, value)

    await db.commit()
    await db.refresh(profile)

    logger.info(
        "agent_profile_saved",
        site_id=site_id,
        created=created,
        enabled=profile.enabled,
    )
    return profile
