"""Known-contacts upload — the site owner's existing-customer / prior-lead list.

Emails are normalized + HMAC-hashed (services/known_hash.py) and stored as a
blind index; we never persist the owner's plaintext contact list. Identified
visitors whose email hash matches an entry are flagged "Known" on the Visitors
page (matching lives in routers/visitors.py).
"""

import csv
import io
import re
import uuid

import structlog
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.dependencies import get_current_user, verify_site_access as _verify_site_access
from apps.api.models.database import get_db
from apps.api.models.known_contact import KnownContact
from apps.api.models.site import Site
from apps.api.models.user import User
from apps.api.services.known_hash import email_hash, normalize_email

logger = structlog.get_logger()

router = APIRouter()

# Defensive caps so a giant or malformed upload can't exhaust memory.
MAX_FILE_BYTES = 10 * 1024 * 1024  # 10 MB
MAX_EMAILS = 50_000

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _looks_like_email(value: str) -> bool:
    return bool(_EMAIL_RE.match(value))


class KnownUploadResult(BaseModel):
    inserted: int  # newly added hashes
    skipped: int  # valid emails already present (deduped against existing)
    total: int  # distinct valid emails found in the file
    truncated: bool = False  # file had more than MAX_EMAILS distinct emails


class KnownCountOut(BaseModel):
    count: int


class KnownDeleteResult(BaseModel):
    deleted: int


@router.post("/{site_id}/known-contacts/upload", response_model=KnownUploadResult)
async def upload_known_contacts(
    site_id: str,
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> KnownUploadResult:
    """Upload a CSV of the contacts you already know. Any cell that looks like an
    email is taken (so a one-column or full CRM export both work). Stored hashed,
    not plaintext; re-uploading the same address is a no-op."""
    await _verify_site_access(db, site_id, user)

    raw = await file.read()
    if len(raw) > MAX_FILE_BYTES:
        raise HTTPException(status_code=413, detail="File too large (max 10 MB)")

    # utf-8-sig drops a leading BOM that Excel exports add.
    text = raw.decode("utf-8-sig", errors="ignore")
    emails: set[str] = set()
    truncated = False
    for row in csv.reader(io.StringIO(text)):
        for cell in row:
            candidate = normalize_email(cell)
            if _looks_like_email(candidate):
                emails.add(candidate)
                break  # one email per row is enough
        if len(emails) >= MAX_EMAILS:
            truncated = True
            break

    total = len(emails)
    if not emails:
        return KnownUploadResult(inserted=0, skipped=0, total=0, truncated=truncated)

    # PII: only the HMAC hash is persisted — never the plaintext address.
    rows = [
        {"id": uuid.uuid4(), "site_id": site_id, "email_hash": email_hash(e), "source": "csv"}
        for e in emails
    ]
    stmt = (
        pg_insert(KnownContact)
        .values(rows)
        .on_conflict_do_nothing(index_elements=["site_id", "email_hash"])
        .returning(KnownContact.id)
    )
    result = await db.execute(stmt)
    inserted = len(result.fetchall())
    await db.commit()

    logger.info(
        "known_contacts_uploaded",
        site_id=site_id,
        inserted=inserted,
        skipped=total - inserted,
        total=total,
    )  # count only — no email/PII in logs
    return KnownUploadResult(
        inserted=inserted, skipped=total - inserted, total=total, truncated=truncated
    )


@router.get("/{site_id}/known-contacts/count", response_model=KnownCountOut)
async def known_contacts_count(
    site_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> KnownCountOut:
    await _verify_site_access(db, site_id, user)
    n = (
        await db.execute(
            select(func.count()).select_from(KnownContact).where(KnownContact.site_id == site_id)
        )
    ).scalar() or 0
    return KnownCountOut(count=n)


@router.delete("/{site_id}/known-contacts", response_model=KnownDeleteResult)
async def clear_known_contacts(
    site_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> KnownDeleteResult:
    await _verify_site_access(db, site_id, user)
    result = await db.execute(delete(KnownContact).where(KnownContact.site_id == site_id))
    await db.commit()
    return KnownDeleteResult(deleted=result.rowcount or 0)
