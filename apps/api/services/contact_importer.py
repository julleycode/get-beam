"""CSV contact import — turn a customer's own contact list into phantom visitors.

Identity-honesty Phase 4. Each imported row becomes a PHANTOM ``Visitor`` row
(``visitor_id = f"import:{contact_id}"``, ``is_imported_contact = True``) plus a
seeded ``IdentifiedVisitor`` marked ``identity_status = "identified"`` with
``resolution_provider = "contact_import"``. Reusing the ordinary visitor tables
(rather than a bespoke contacts table) means every existing join — segments,
campaign_sender, dashboards, aggregator — works unmodified.

Merge-on-click needs NO new code here: if the contact later actually visits and
resolves to the same email, ``identity_resolver._save_identified``'s existing
email-dedup branch marks the click-derived row ``"merged"`` and points its
``canonical_visitor_id`` at this phantom. The only obligation on this module is
to write the email lowercase-normalized (matching every other provider's
convention) so the dedup lookup finds it.

PII: ``IdentifiedVisitor.email`` is written as PLAINTEXT, exactly like every
other resolution provider (rb2b/leadpipe/capturify/form_capture/manual). The
enforced guardrail is that the raw address is never logged — counts and domains
only.
"""

import csv
import io
import re
import uuid
from datetime import datetime

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.models.visitor import IdentifiedVisitor, Visitor

logger = structlog.get_logger()

# Business cap: a site may hold at most this many imported contacts. An upload
# that would cross it is REJECTED WHOLE — never truncated to a partial import.
MAX_IMPORTED_CONTACTS_PER_SITE = 5_000

# Defensive caps, applied BEFORE any business logic so a giant or malformed file
# cannot exhaust memory before the row-count check even runs. Mirrors
# known_contacts.py's MAX_FILE_BYTES/MAX_EMAILS pattern — necessary because
# IngestBodySizeLimitMiddleware guards ONLY /api/v1/events/ingest, so no
# middleware-level body cap applies to this route.
MAX_FILE_BYTES = 2 * 1024 * 1024  # 2 MB — ample for 5,000 name,email rows
MAX_ROWS_SCANNED = 20_000  # stop reading long before memory pressure

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

IMPORT_PROVIDER = "contact_import"


class ContactImportError(Exception):
    """Raised for a whole-upload rejection (caps, quota). Carries an HTTP status."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def looks_like_email(value: str) -> bool:
    """Lightweight email-shape check (same shape as known_contacts._looks_like_email)."""
    return bool(_EMAIL_RE.match(value or ""))


def normalize_email(value: str | None) -> str:
    return (value or "").strip().lower()


def parse_contacts_csv(raw: bytes) -> tuple[list[dict], list[dict]]:
    """Parse a CSV into (valid_contacts, rejected_rows).

    Accepts either a header row naming ``email``/``name`` columns, or a bare
    ``name,email`` / single-column layout — any cell that looks like an email is
    taken as the address, and (when a header is absent) the first non-email cell
    on the row is taken as the name.

    Rejected rows carry a per-row reason instead of being silently dropped, so
    the caller can report malformed data back to the user rather than writing
    garbage into IdentifiedVisitor.email (which would both poison the merge
    dedup match and burn quota on an unemailable row).
    """
    if len(raw) > MAX_FILE_BYTES:
        raise ContactImportError(
            413, f"File too large (max {MAX_FILE_BYTES // (1024 * 1024)} MB)"
        )

    # utf-8-sig drops the BOM Excel exports prepend.
    text = raw.decode("utf-8-sig", errors="ignore")

    valid: list[dict] = []
    rejected: list[dict] = []
    seen: set[str] = set()

    for line_no, row in enumerate(csv.reader(io.StringIO(text)), start=1):
        if line_no > MAX_ROWS_SCANNED:
            raise ContactImportError(
                413, f"Too many rows (max {MAX_ROWS_SCANNED} scanned)"
            )
        cells = [c.strip() for c in row if c is not None]
        if not any(cells):
            continue

        email = ""
        name = ""
        for cell in cells:
            candidate = normalize_email(cell)
            if not email and looks_like_email(candidate):
                email = candidate
            elif not name and cell and not looks_like_email(normalize_email(cell)):
                name = cell

        if not email:
            # A header row ("name","email") lands here too — it is simply a row
            # with no email-shaped cell, and is reported rather than imported.
            rejected.append({"line": line_no, "reason": "no valid email in row"})
            continue
        if email in seen:
            rejected.append({"line": line_no, "reason": "duplicate email in file"})
            continue

        seen.add(email)
        valid.append({"email": email, "full_name": name or None})

    return valid, rejected


async def count_imported_contacts(db: AsyncSession, site_id: str) -> int:
    return (
        await db.execute(
            select(func.count())
            .select_from(Visitor)
            .where(Visitor.site_id == site_id, Visitor.is_imported_contact.is_(True))
        )
    ).scalar() or 0


async def import_contacts(db: AsyncSession, site_id: str, raw: bytes) -> dict:
    """Parse + validate + persist a CSV import for one site.

    Whole-upload semantics: if the site's existing imported-contact count plus
    the new valid rows would exceed MAX_IMPORTED_CONTACTS_PER_SITE, nothing is
    written and a clear error naming the limit is raised.
    """
    valid, rejected = parse_contacts_csv(raw)

    existing = await count_imported_contacts(db, site_id)
    if existing + len(valid) > MAX_IMPORTED_CONTACTS_PER_SITE:
        raise ContactImportError(
            400,
            (
                f"Import rejected: this site already has {existing} imported "
                f"contacts and this file adds {len(valid)}, which exceeds the "
                f"limit of {MAX_IMPORTED_CONTACTS_PER_SITE} per site. "
                "No contacts were imported."
            ),
        )

    # Skip addresses already imported for this site — re-uploading the same list
    # must be a no-op, not a duplicate-row generator.
    already: set[str] = set()
    if valid:
        rows = (
            await db.execute(
                select(func.lower(IdentifiedVisitor.email)).where(
                    IdentifiedVisitor.site_id == site_id,
                    IdentifiedVisitor.email.in_([c["email"] for c in valid]),
                )
            )
        ).scalars().all()
        already = {r for r in rows if r}

    now = datetime.utcnow()
    imported = 0
    for contact in valid:
        if contact["email"] in already:
            rejected.append({"line": None, "reason": "already imported"})
            continue
        contact_id = uuid.uuid4()  # minted BEFORE the row — visitor_id embeds it
        visitor_id = f"import:{contact_id}"
        db.add(
            Visitor(
                site_id=site_id,
                visitor_id=visitor_id,
                first_seen=now,
                last_seen=now,
                is_imported_contact=True,
                identity_status="identified",
                pages_visited=[],
            )
        )
        db.add(
            IdentifiedVisitor(
                site_id=site_id,
                visitor_id=visitor_id,
                email=contact["email"],  # lowercase-normalized; plaintext by convention
                full_name=contact["full_name"],
                resolution_provider=IMPORT_PROVIDER,
                confidence_score=1.0,
            )
        )
        imported += 1

    await db.commit()

    logger.info(
        "contacts_imported",
        site_id=site_id,
        imported=imported,
        rejected=len(rejected),
        total_after=existing + imported,
    )  # counts only — never the addresses themselves

    return {
        "imported": imported,
        "rejected": len(rejected),
        "rejected_rows": rejected[:50],
        "total": existing + imported,
        "limit": MAX_IMPORTED_CONTACTS_PER_SITE,
    }
