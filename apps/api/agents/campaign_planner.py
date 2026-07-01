import json

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.config import settings
from apps.api.agents.prompt_safety import clean_text, extract_json, sanitize_profiles, wrap_untrusted
from apps.api.services.gemini_client import gemini_generate
from apps.api.models.campaign import Campaign
from apps.api.models.segment import Segment

logger = structlog.get_logger()

CAMPAIGN_PLANNING_PROMPT = """
You are an expert growth marketer creating a retargeting campaign plan.

## Segment
Name: {segment_name}
Description: {segment_description}
Size: {visitor_count} people
Characteristics: {characteristics_json}
Recommended Channels: {channels}
Messaging Angle: {messaging_angle}

## Enriched Visitor Profiles in This Segment
{visitor_profiles_json}

## Available Channels
- Email (via Resend API, direct send)
- LinkedIn (organic: connection request + note, or export for LinkedIn Ads)
- Twitter/X (organic: reply/mention, or export for X Ads)
- Meta Ads (export CSV for Custom Audiences)
- Google Ads (export CSV for Customer Match)
- Social Reply (reply to visitor's recent posts via EasyEngage — requires connected social account)
- Social DM (direct message on Twitter/LinkedIn via EasyEngage — requires connected social account)

## Connected Social Accounts
{connected_accounts_info}

## Social Engagement Note
If a visitor has a linkedin_url or twitter_handle, and the user has a connected
social account on that platform, prefer organic social outreach (reply or DM)
over cold email — it feels more personal and gets higher response rates.
Use the GBrain AI to generate personalized replies in the user's voice.

## Personalization From Recent Content
Some visitor profiles include a `recent_content` field summarizing what that
person (or their company) recently posted on YouTube, Reddit, or X, or a short
research summary. When present, weave it into the copy NATURALLY — reference a
specific recent video/post/topic to show genuine attention. Rules:
- Only use `recent_content` that is actually present in the profile. NEVER
  invent, assume, or fabricate posts, videos, or topics.
- Keep it subtle and human — a passing, specific reference, not a summary dump.
- If a profile has no `recent_content`, write normal copy for that visitor.

## Your Task
Create a campaign plan with:
1. Channel priority order (which to use first, second, etc.)
2. For each channel, write the actual message/copy ready to send
3. Timing: when to send each touchpoint
4. Follow up sequence: what happens if no response after 3 days

## Output Format (JSON only, no markdown)
{{
  "campaign_name": "Descriptive campaign name",
  "segment_id": "{segment_id}",
  "total_touchpoints": 3,
  "touchpoints": [
    {{
      "order": 1,
      "channel": "email",
      "delay_hours_from_start": 0,
      "subject": "Email subject line",
      "body": "Full email body. Use {{{{first_name}}}} for personalization.",
      "personalization_fields": ["first_name", "company_name"],
      "cta": "What action you want them to take"
    }},
    {{
      "order": 2,
      "channel": "linkedin",
      "delay_hours_from_start": 48,
      "connection_note": "LinkedIn connection request note (max 300 chars)",
      "followup_message": "Message after connection accepted",
      "personalization_fields": ["first_name", "job_title"]
    }},
    {{
      "order": 3,
      "channel": "social_reply",
      "delay_hours_from_start": 24,
      "platform": "twitter",
      "reply_strategy": "conversational",
      "context": "What to look for in their recent posts to reply to",
      "personalization_fields": ["first_name", "industry"]
    }},
    {{
      "order": 4,
      "channel": "meta_ads",
      "delay_hours_from_start": 0,
      "ad_headline": "Ad headline",
      "ad_body": "Ad body copy",
      "audience_description": "How to set up the custom audience"
    }}
  ],
  "success_metric": "What defines success for this campaign",
  "estimated_reach": "Realistic estimate of how many people this will actually reach"
}}
"""


async def plan_campaign(
    db: AsyncSession,
    segment: Segment,
    visitor_profiles: list[dict],
    connected_accounts: list[dict] | None = None,
) -> Campaign:
    # Build connected accounts info for the prompt
    if connected_accounts:
        accounts_info = ", ".join(
            f"{a['platform']} (@{a['username']})" for a in connected_accounts
        )
    else:
        accounts_info = "None — social reply/DM channels are not available"

    # Visitor-controlled text (page URLs, bios, company names) is sanitized
    # and explicitly delimited as untrusted before prompt insertion.
    safe_profiles = sanitize_profiles(visitor_profiles)
    # Segment fields are themselves LLM-derived from visitor data (second-
    # order injection vector) — delimit/cap them the same way.
    prompt = CAMPAIGN_PLANNING_PROMPT.format(
        segment_name=clean_text(segment.name, 200),
        segment_description=clean_text(segment.description or "", 500),
        visitor_count=segment.visitor_count,
        characteristics_json=wrap_untrusted(json.dumps(segment.characteristics, default=str)),
        channels=json.dumps(segment.recommended_channels, default=str),
        messaging_angle=clean_text(segment.messaging_angle or "", 300),
        visitor_profiles_json=wrap_untrusted(
            json.dumps(safe_profiles, indent=2, default=str)
        ),
        segment_id=str(segment.id),
        connected_accounts_info=accounts_info,
    )

    if not settings.gemini_api_key:
        raise RuntimeError(
            "GEMINI_API_KEY is not configured — cannot plan campaign"
        )

    text = await gemini_generate(prompt, max_output_tokens=4096)
    plan = extract_json(text)
    # Defensive shape checks: touchpoints must be a list of dicts (the send
    # path and detail UI iterate them), and the name must fit its column.
    touchpoints = plan.get("touchpoints")
    if not isinstance(touchpoints, list):
        plan["touchpoints"] = []
    else:
        plan["touchpoints"] = [tp for tp in touchpoints if isinstance(tp, dict)]

    campaign = Campaign(
        site_id=segment.site_id,
        segment_id=segment.id,
        name=str(plan.get("campaign_name") or f"Campaign for {segment.name}")[:200],
        status="draft",
        plan=plan,
    )
    db.add(campaign)
    await db.commit()

    logger.info("campaign_planned", segment_id=str(segment.id), campaign_id=str(campaign.id))
    return campaign
