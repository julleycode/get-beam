import csv
import hashlib
import io

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.models.enrichment import EnrichmentProfile
from apps.api.models.segment import SegmentMember
from apps.api.models.visitor import IdentifiedVisitor

logger = structlog.get_logger()


def _sha256(value: str) -> str:
    return hashlib.sha256(value.strip().lower().encode()).hexdigest()


async def _get_segment_visitors(
    db: AsyncSession, segment_id: str
) -> list[dict]:
    members_result = await db.execute(
        select(SegmentMember).where(SegmentMember.segment_id == segment_id)
    )
    members = list(members_result.scalars().all())

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


async def export_meta_csv(db: AsyncSession, segment_id: str) -> str:
    visitors = await _get_segment_visitors(db, segment_id)
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


async def export_google_csv(db: AsyncSession, segment_id: str) -> str:
    visitors = await _get_segment_visitors(db, segment_id)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Email", "Phone", "First Name", "Last Name", "Country", "Zip"])

    for v in visitors:
        writer.writerow([
            v["email"], v["phone"], v["first_name"],
            v["last_name"], v["country"], "",
        ])

    logger.info("csv_exported", platform="google", segment_id=segment_id, count=len(visitors))
    return output.getvalue()


async def export_linkedin_csv(db: AsyncSession, segment_id: str) -> str:
    visitors = await _get_segment_visitors(db, segment_id)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["email", "companyName", "jobTitle", "firstName", "lastName"])

    for v in visitors:
        writer.writerow([
            v["email"], v["company_name"], v["job_title"],
            v["first_name"], v["last_name"],
        ])

    logger.info("csv_exported", platform="linkedin", segment_id=segment_id, count=len(visitors))
    return output.getvalue()
