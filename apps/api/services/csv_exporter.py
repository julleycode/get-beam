import csv
import hashlib
import io

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.models.enrichment import EnrichmentProfile
from apps.api.models.segment import SegmentMember
from apps.api.models.visitor import IdentifiedVisitor, Visitor
from apps.api.config import settings
from apps.api.services.identity_classification import (
    is_emailable_identity,
    is_graph_candidate_provider,
    is_verified_identity,
)
from apps.api.services.suppression import is_email_suppressed

logger = structlog.get_logger()


def _sha256(value: str) -> str:
    return hashlib.sha256(value.strip().lower().encode()).hexdigest()


def _csv_safe(value) -> str:
    """Neutralize CSV formula injection: a cell starting with =, +, -, @ (or a
    leading tab/CR) is prefixed with an apostrophe so a spreadsheet can't run it
    as a formula when the export is opened."""
    s = "" if value is None else str(value)
    if s and s[0] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + s
    return s


async def _get_segment_visitors(
    db: AsyncSession, segment_id: str, exclude_known: bool = False
) -> list[dict]:
    members_result = await db.execute(
        select(SegmentMember).where(SegmentMember.segment_id == segment_id)
    )
    members = list(members_result.scalars().all())

    # Net-new targeting: optionally drop contacts the owner already has in their
    # CRM (the known-contacts list). Hash-vs-hash, one query for the whole site —
    # matches the privacy pattern of the suppression check below.
    known_hashes: set[str] = set()
    if exclude_known and members:
        from apps.api.models.known_contact import KnownContact
        from apps.api.services.known_hash import email_hash as _known_email_hash

        kc_rows = await db.execute(
            select(KnownContact.email_hash).where(
                KnownContact.site_id == members[0].site_id
            )
        )
        known_hashes = {h for (h,) in kc_rows.all()}

    visitors: list[dict] = []
    for member in members:
        id_result = await db.execute(
            select(IdentifiedVisitor).where(
                IdentifiedVisitor.site_id == member.site_id,
                IdentifiedVisitor.visitor_id == member.visitor_id,
                # Compliance: never export unsubscribed / hard-bounced contacts
                # to ad audiences. IS NOT TRUE also keeps non-suppressed rows if
                # the column were ever NULL (it is NOT NULL per the model; this
                # form is just defensive against schema drift).
                IdentifiedVisitor.do_not_email.is_not(True),
            )
        )
        identified = id_result.scalar_one_or_none()
        if not identified or not identified.email:
            continue

        # Already in the owner's CRM → not a net-new lead; skip when requested.
        if known_hashes and _known_email_hash(identified.email) in known_hashes:
            continue

        # Never export a company-level guess (hunter/apollo) — it's a random
        # employee at the visitor's company, not the visitor; pushing it to ad
        # audiences / CRM spams someone who never visited.
        exportable = is_emailable_identity(
            identified.resolution_provider,
            getattr(identified, "source_agent_visit_id", None),
            getattr(identified, "is_abuse_flagged", False),
        )
        # D5/D10 confirm-gate (see config.candidate_outreach_enabled). Only
        # queried for graph-candidate providers, so the common path costs nothing.
        # Additive-restrictive: can narrow the export, never widen it.
        if (
            exportable
            and is_graph_candidate_provider(identified.resolution_provider)
            and not settings.candidate_outreach_enabled
        ):
            identity_status = (
                await db.execute(
                    select(Visitor.identity_status).where(
                        Visitor.site_id == member.site_id,
                        Visitor.visitor_id == member.visitor_id,
                    )
                )
            ).scalar_one_or_none()
            exportable = is_verified_identity(identity_status)
        if not exportable:
            continue

        # Compliance: never export contacts on the privacy suppression list
        # (CCPA "Do Not Sell"). This is on top of the do_not_email filter above.
        if await is_email_suppressed(db, identified.email, "do_not_sell"):
            continue

        enrich_result = await db.execute(
            select(EnrichmentProfile).where(
                EnrichmentProfile.site_id == member.site_id,
                EnrichmentProfile.visitor_id == member.visitor_id,
            )
        )
        enriched = enrich_result.scalar_one_or_none()

        name_parts = (identified.full_name or "").split(" ", 1)
        first_name = name_parts[0] if name_parts else ""
        last_name = name_parts[1] if len(name_parts) > 1 else ""

        visitors.append({
            "email": identified.email,
            "first_name": first_name,
            "last_name": last_name,
            "phone": identified.phone or "",
            "city": identified.city or "",
            "region": identified.region or "",
            "country": identified.country or "",
            "company_name": enriched.company_name if enriched else "",
            "job_title": enriched.job_title if enriched else "",
        })

    return visitors


async def export_meta_csv(db: AsyncSession, segment_id: str, exclude_known: bool = False) -> str:
    visitors = await _get_segment_visitors(db, segment_id, exclude_known)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["email", "phone", "fn", "ln", "ct", "st", "country", "zip"])

    for v in visitors:
        writer.writerow([
            _sha256(v["email"]),
            _sha256(v["phone"]) if v["phone"] else "",
            _sha256(v["first_name"]) if v["first_name"] else "",
            _sha256(v["last_name"]) if v["last_name"] else "",
            _sha256(v["city"]) if v["city"] else "",
            _sha256(v["region"]) if v["region"] else "",
            _sha256(v["country"]) if v["country"] else "",
            "",
        ])

    logger.info("csv_exported", platform="meta", segment_id=segment_id, count=len(visitors))
    return output.getvalue()


async def export_google_csv(db: AsyncSession, segment_id: str, exclude_known: bool = False) -> str:
    visitors = await _get_segment_visitors(db, segment_id, exclude_known)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Email", "Phone", "First Name", "Last Name", "Country", "Zip"])

    for v in visitors:
        writer.writerow([
            _csv_safe(v["email"]), _csv_safe(v["phone"]), _csv_safe(v["first_name"]),
            _csv_safe(v["last_name"]), _csv_safe(v["country"]), "",
        ])

    logger.info("csv_exported", platform="google", segment_id=segment_id, count=len(visitors))
    return output.getvalue()


async def export_linkedin_csv(db: AsyncSession, segment_id: str, exclude_known: bool = False) -> str:
    visitors = await _get_segment_visitors(db, segment_id, exclude_known)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["email", "companyName", "jobTitle", "firstName", "lastName"])

    for v in visitors:
        writer.writerow([
            _csv_safe(v["email"]), _csv_safe(v["company_name"]), _csv_safe(v["job_title"]),
            _csv_safe(v["first_name"]), _csv_safe(v["last_name"]),
        ])

    logger.info("csv_exported", platform="linkedin", segment_id=segment_id, count=len(visitors))
    return output.getvalue()
