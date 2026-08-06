"""Privacy / compliance endpoints — the suppression list (GDPR/CCPA).

Admin-only. An operator records a "Do Not Sell" (CCPA) or "Do Not Process"
(GDPR) request here; the identity resolver and the CSV exporter then honor it
automatically, and existing data for that email is suppressed immediately
(cascade). Only a hash of the email is stored, so the list cannot be read back
as plaintext addresses.
"""

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.config import settings
from apps.api.dependencies import require_admin
from apps.api.models.database import get_db
from apps.api.models.user import User
from apps.api.schemas.privacy import (
    ErasureQueueHealthOut,
    GraphIdentityLookupOut,
    SuppressionCreate,
    SuppressionOut,
)
from apps.api.services.graph_erasure import lookup_graph_identity, queue_health
from apps.api.services.suppression import (
    VALID_SCOPES,
    add_suppression,
    list_suppressions,
    remove_suppression,
)

router = APIRouter()
logger = structlog.get_logger()


@router.get("/graph-identity", response_model=GraphIdentityLookupOut)
async def get_graph_identity(
    email: str | None = Query(None, description="Plaintext email to look up"),
    fingerprint: str | None = Query(None, description="Browser fingerprint hash"),
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> GraphIdentityLookupOut:
    """Is this person still in the cross-tenant graph, and which sites contributed?

    PLATFORM-OPERATOR ONLY. This endpoint IS an existence oracle over the shared
    graph — that is precisely its purpose for erasure verification — so it must
    never be tenant-reachable. Gated twice: an explicit feature flag (default
    OFF) plus the admin dependency. With the flag off it answers 404 rather than
    revealing that the route exists.
    """
    if not settings.graph_identity_lookup_enabled:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    try:
        return GraphIdentityLookupOut(
            **await lookup_graph_identity(db, email=email, fingerprint=fingerprint)
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)
        ) from e


@router.get("/erasure-queue-health", response_model=ErasureQueueHealthOut)
async def get_erasure_queue_health(
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> ErasureQueueHealthOut:
    """Erasure queue counters for an operator. Counts and ages only, no PII.

    ``failed > 0`` is a compliance event, not a backlog item — the caller was
    already told the erasure was accepted. Response: read the affected rows'
    last_error (PII-sanitised, safe to read), fix the cause, then re-enqueue by
    resetting those rows to status='pending' with attempts=0 (the sweep re-claims
    them and the operation is idempotent). If the cause cannot be fixed, the
    request is unfulfilled and must be escalated, never left silently in failed.
    """
    if not settings.graph_identity_lookup_enabled:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    return ErasureQueueHealthOut(**await queue_health(db))


@router.get("/suppressions", response_model=list[SuppressionOut])
async def get_suppressions(
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> list[SuppressionOut]:
    """List suppression entries (hashes only — no plaintext emails)."""
    return [SuppressionOut.model_validate(e) for e in await list_suppressions(db)]


@router.post("/suppressions", status_code=status.HTTP_201_CREATED)
async def create_suppression(
    body: SuppressionCreate,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Add an email to the suppression list and cascade to existing data."""
    if body.scope not in VALID_SCOPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"invalid scope; must be one of {sorted(VALID_SCOPES)}",
        )
    if "@" not in (body.email or ""):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="a valid email address is required",
        )
    result = await add_suppression(
        db, body.email, scope=body.scope, reason=body.reason, requested_by=admin.email
    )
    return {"status": "suppressed", **result}


@router.delete("/suppressions")
async def delete_suppression(
    email: str = Query(..., description="Email to un-suppress"),
    scope: str = Query("all"),
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Remove a suppression entry. Note: already-applied do_not_email /
    do_not_resolve flags are NOT reversed — un-suppressing never silently
    re-enables processing of someone who once opted out."""
    removed = await remove_suppression(db, email, scope)
    return {"status": "removed", "count": removed}
