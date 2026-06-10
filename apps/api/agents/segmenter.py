import json
import uuid

import anthropic
from anthropic.types import TextBlock
import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.config import settings
from apps.api.agents.prompt_safety import extract_json, sanitize_profiles, wrap_untrusted
from apps.api.models.enrichment import EnrichmentProfile
from apps.api.models.segment import Segment, SegmentMember
from apps.api.models.visitor import IdentifiedVisitor, Visitor

logger = structlog.get_logger()

SEGMENTATION_PROMPT = """
You are a growth marketing strategist analyzing website visitors for retargeting.

## Website Context
Site: {site_name}
Site Description: {site_description}
Site Category: {site_category}

## Visitor Batch (JSON)
{visitor_profiles_json}

## Your Task
Analyze these visitors and group them into 2 to 5 actionable segments. Each segment must be:
1. Large enough to be worth targeting (at least 3 visitors)
2. Distinct enough that they need different messaging
3. Actionable (you can actually reach them somewhere)

## Output Format (JSON only, no markdown)
{{
  "segments": [
    {{
      "segment_id": "seg_001",
      "name": "Short descriptive name",
      "description": "Who these people are and why they are grouped",
      "visitor_ids": ["id1", "id2"],
      "characteristics": {{
        "common_job_titles": [],
        "common_industries": [],
        "common_behaviors": [],
        "avg_intent_score": 0
      }},
      "recommended_channels": ["email", "linkedin", "twitter", "meta_ads", "google_ads"],
      "messaging_angle": "What messaging would resonate with this group",
      "priority": "high/medium/low"
    }}
  ],
  "unsegmented_visitor_ids": ["ids that dont fit any segment"],
  "reasoning": "Brief explanation of segmentation logic"
}}
"""


async def build_visitor_profiles(
    db: AsyncSession, site_id: str, visitors: list[Visitor]
) -> list[dict]:
    from sqlalchemy import select

    visitor_ids = [v.visitor_id for v in visitors]

    # Batch-fetch all identified visitors in one query (fixes N+1)
    id_result = await db.execute(
        select(IdentifiedVisitor).where(
            IdentifiedVisitor.site_id == site_id,
            IdentifiedVisitor.visitor_id.in_(visitor_ids),
        )
    )
    id_map = {iv.visitor_id: iv for iv in id_result.scalars().all()}

    # Batch-fetch all enrichment profiles in one query (fixes N+1)
    enrich_result = await db.execute(
        select(EnrichmentProfile).where(
            EnrichmentProfile.site_id == site_id,
            EnrichmentProfile.visitor_id.in_(visitor_ids),
        )
    )
    enrich_map = {ep.visitor_id: ep for ep in enrich_result.scalars().all()}

    profiles = []
    for v in visitors:
        profile: dict = {
            "visitor_id": v.visitor_id,
            "intent_score": v.intent_score,
            "total_pageviews": v.total_pageviews,
            "total_sessions": v.total_sessions,
            "pages_visited": v.pages_visited,
            "device_type": v.device_type,
            "country_code": v.country_code,
        }
        identified = id_map.get(v.visitor_id)
        if identified:
            profile["email"] = identified.email
            profile["full_name"] = identified.full_name
            profile["city"] = identified.city
            profile["country"] = identified.country

        enriched = enrich_map.get(v.visitor_id)
        if enriched:
            profile["job_title"] = enriched.job_title
            profile["company_name"] = enriched.company_name
            profile["industry"] = enriched.industry
            profile["seniority_level"] = enriched.seniority_level
            profile["linkedin_url"] = enriched.linkedin_url
            profile["twitter_handle"] = enriched.twitter_handle
            profile["linkedin_headline"] = enriched.linkedin_headline
            profile["twitter_bio"] = enriched.twitter_bio

        profiles.append(profile)
    return profiles


async def run_segmentation(
    db: AsyncSession,
    site_id: str,
    site_name: str,
    site_description: str,
    site_category: str,
    visitors: list[Visitor],
) -> list[Segment]:
    profiles = await build_visitor_profiles(db, site_id, visitors)

    # Visitor-controlled text (page URLs, bios, company names) is sanitized
    # and explicitly delimited as untrusted before prompt insertion.
    safe_profiles = sanitize_profiles(profiles)
    prompt = SEGMENTATION_PROMPT.format(
        site_name=site_name,
        site_description=site_description or "Not provided",
        site_category=site_category or "General",
        visitor_profiles_json=wrap_untrusted(
            json.dumps(safe_profiles, indent=2, default=str)
        ),
    )

    if not settings.anthropic_api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not configured — cannot run segmentation"
        )

    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    message = await client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )
    first = message.content[0]
    if not isinstance(first, TextBlock):
        raise ValueError(f"Unexpected content block type: {type(first)}")
    result = extract_json(first.text)

    # Only visitor ids from the input batch may become members — the model
    # can hallucinate ids (segment_members has no FK), and a poisoned profile
    # could try to smuggle ids in.
    input_ids = {v.visitor_id for v in visitors}

    segments: list[Segment] = []
    for seg_data in result.get("segments", []):
        if not isinstance(seg_data, dict) or not seg_data.get("name"):
            logger.warning("segmenter_invalid_segment_skipped", site_id=site_id)
            continue
        valid_ids = [
            vid for vid in seg_data.get("visitor_ids", []) if vid in input_ids
        ]
        dropped = len(seg_data.get("visitor_ids", [])) - len(valid_ids)
        if dropped:
            logger.warning(
                "segmenter_hallucinated_ids_dropped",
                site_id=site_id,
                dropped=dropped,
            )
        segment = Segment(
            site_id=site_id,
            name=str(seg_data["name"])[:200],
            description=seg_data.get("description"),
            characteristics=seg_data.get("characteristics", {}),
            recommended_channels=seg_data.get("recommended_channels", []),
            messaging_angle=seg_data.get("messaging_angle"),
            priority=seg_data.get("priority", "medium"),
            visitor_count=len(valid_ids),
        )
        db.add(segment)
        await db.flush()

        for vid in valid_ids:
            member = SegmentMember(
                segment_id=segment.id,
                visitor_id=vid,
                site_id=site_id,
            )
            db.add(member)

        segments.append(segment)

    await db.commit()
    logger.info("segmentation_complete", site_id=site_id, segments=len(segments))
    return segments


def _mock_segmentation(profiles: list[dict]) -> dict:
    if len(profiles) < 3:
        return {"segments": [], "unsegmented_visitor_ids": [p["visitor_id"] for p in profiles], "reasoning": "Not enough visitors"}

    high_intent = [p for p in profiles if p["intent_score"] >= 60]
    low_intent = [p for p in profiles if p["intent_score"] < 60]

    segments = []
    if len(high_intent) >= 3:
        segments.append({
            "segment_id": "seg_001",
            "name": "High-Intent Evaluators",
            "description": "Visitors with strong engagement signals who are actively evaluating the product",
            "visitor_ids": [p["visitor_id"] for p in high_intent],
            "characteristics": {
                "common_job_titles": list({p.get("job_title", "Unknown") for p in high_intent}),
                "common_industries": list({p.get("industry", "Unknown") for p in high_intent}),
                "common_behaviors": ["Multiple sessions", "Deep scroll depth", "Pricing page visits"],
                "avg_intent_score": sum(p["intent_score"] for p in high_intent) / len(high_intent),
            },
            "recommended_channels": ["email", "linkedin"],
            "messaging_angle": "Direct value proposition with social proof and case studies",
            "priority": "high",
        })

    if len(low_intent) >= 3:
        segments.append({
            "segment_id": "seg_002",
            "name": "Early-Stage Browsers",
            "description": "Visitors showing initial interest but haven't fully engaged yet",
            "visitor_ids": [p["visitor_id"] for p in low_intent],
            "characteristics": {
                "common_job_titles": list({p.get("job_title", "Unknown") for p in low_intent}),
                "common_industries": list({p.get("industry", "Unknown") for p in low_intent}),
                "common_behaviors": ["Single session", "Light browsing"],
                "avg_intent_score": sum(p["intent_score"] for p in low_intent) / len(low_intent),
            },
            "recommended_channels": ["meta_ads", "google_ads"],
            "messaging_angle": "Educational content and awareness building",
            "priority": "medium",
        })

    unsegmented = [p["visitor_id"] for p in profiles if not any(
        p["visitor_id"] in s["visitor_ids"] for s in segments
    )]

    return {
        "segments": segments,
        "unsegmented_visitor_ids": unsegmented,
        "reasoning": "Segmented by intent score threshold (60+) into evaluators vs browsers",
    }
