"""Imported contacts — bring your own contact list in as contactable leads.

DISTINCT from ``routers/known_contacts.py``, which is a hash-only EXCLUSION
filter (no plaintext email retained, no Visitor row ever created, used to flag
an already-identified visitor as an existing customer). This router does the
opposite: it CREATES identities. Each uploaded row becomes a phantom visitor
with a real, contactable identity and a tokenized link, so a customer can reach
their own list through Beam's existing campaign guardrails before those contacts
ever visit the site.

Product copy must keep the two visibly apart: "Imported Contacts" here vs.
"Known Contacts" there.
"""

import structlog
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.dependencies import get_current_user, verify_site_access
from apps.api.models.database import get_db
from apps.api.models.user import User
from apps.api.models.visitor import IdentifiedVisitor, Visitor
from apps.api.services.contact_importer import (
    MAX_FILE_BYTES,
    MAX_IMPORTED_CONTACTS_PER_SITE,
    ContactImportError,
    count_imported_contacts,
    import_contacts,
)
from apps.api.services.link_decorator import generate_bid

logger = structlog.get_logger()

router = APIRouter()


class ImportResult(BaseModel):
    imported: int
    rejected: int
    rejected_rows: list[dict]
    total: int
    limit: int


class ImportedContactOut(BaseModel):
    visitor_id: str
    email: str | None
    full_name: str | None
    identity_status: str
    has_link: bool


class ImportedContactDetail(ImportedContactOut):
    tracking_link: str | None


class ImportedContactList(BaseModel):
    contacts: list[ImportedContactOut]
    total: int
    limit: int


def _tracking_link(site_url: str | None, email: str | None) -> str | None:
    """Tokenized link for one contact, via the existing _bid mechanism.

    Derived on read rather than persisted: the token is a pure function of the
    email, so storing it would only create a second copy of the same PII.
    Returns None when ENCRYPTION_KEY is unconfigured (generate_bid raises).
    """
    if not email or not site_url:
        return None
    try:
        bid = generate_bid(email)
    except RuntimeError:
        return None
    sep = "&" if "?" in site_url else "?"
    return f"{site_url}{sep}_bid={bid}"


@router.post("/{site_id}/contacts/import", response_model=ImportResult)
async def import_contacts_csv(
    site_id: str,
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ImportResult:
    """Upload a CSV of contacts you already own (columns: name, email).

    Whole-upload semantics: exceeding the per-site limit rejects the ENTIRE file
    with a clear error — never a partial import.
    """
    await verify_site_access(db, site_id, user)
    # Bounded read: never buffer more than the cap + 1 byte, so a giant upload
    # cannot exhaust memory before the size check runs. No middleware body cap
    # applies to this route (IngestBodySizeLimitMiddleware guards only /ingest).
    raw = await file.read(MAX_FILE_BYTES + 1)
    if len(raw) > MAX_FILE_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File too large (max {MAX_FILE_BYTES // (1024 * 1024)} MB)",
        )
    try:
        result = await import_contacts(db, site_id, raw)
    except ContactImportError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return ImportResult(**result)


@router.get("/{site_id}/contacts", response_model=ImportedContactList)
async def list_imported_contacts(
    site_id: str,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ImportedContactList:
    await verify_site_access(db, site_id, user)
    rows = (
        await db.execute(
            select(Visitor, IdentifiedVisitor)
            .join(
                IdentifiedVisitor,
                (IdentifiedVisitor.site_id == Visitor.site_id)
                & (IdentifiedVisitor.visitor_id == Visitor.visitor_id),
                isouter=True,
            )
            .where(Visitor.site_id == site_id, Visitor.is_imported_contact.is_(True))
            .order_by(desc(Visitor.created_at))
            .limit(limit)
            .offset(offset)
        )
    ).all()
    total = await count_imported_contacts(db, site_id)
    return ImportedContactList(
        contacts=[
            ImportedContactOut(
                visitor_id=v.visitor_id,
                email=iv.email if iv else None,
                full_name=iv.full_name if iv else None,
                identity_status=v.identity_status,
                has_link=bool(iv and iv.email),
            )
            for v, iv in rows
        ],
        total=total,
        limit=MAX_IMPORTED_CONTACTS_PER_SITE,
    )


@router.get("/{site_id}/contacts/{visitor_id}", response_model=ImportedContactDetail)
async def get_imported_contact(
    site_id: str,
    visitor_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ImportedContactDetail:
    site = await verify_site_access(db, site_id, user)
    row = (
        await db.execute(
            select(Visitor, IdentifiedVisitor)
            .join(
                IdentifiedVisitor,
                (IdentifiedVisitor.site_id == Visitor.site_id)
                & (IdentifiedVisitor.visitor_id == Visitor.visitor_id),
                isouter=True,
            )
            .where(
                Visitor.site_id == site_id,
                Visitor.visitor_id == visitor_id,
                Visitor.is_imported_contact.is_(True),
            )
        )
    ).first()
    if not row:
        # 404, not 403 — never leak which ids exist (matches verify_site_access).
        raise HTTPException(status_code=404, detail="Contact not found")
    visitor, identified = row
    email = identified.email if identified else None
    return ImportedContactDetail(
        visitor_id=visitor.visitor_id,
        email=email,
        full_name=identified.full_name if identified else None,
        identity_status=visitor.identity_status,
        has_link=bool(email),
        tracking_link=_tracking_link(site.url, email),
    )


@router.get("/{site_id}/contacts-count")
async def imported_contacts_count(
    site_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    await verify_site_access(db, site_id, user)
    return {
        "count": await count_imported_contacts(db, site_id),
        "limit": MAX_IMPORTED_CONTACTS_PER_SITE,
    }
