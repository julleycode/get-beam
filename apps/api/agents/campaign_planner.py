import json

import anthropic
from anthropic.types import TextBlock
import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.config import settings
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

    prompt = CAMPAIGN_PLANNING_PROMPT.format(
        segment_name=segment.name,
        segment_description=segment.description or "",
        visitor_count=segment.visitor_count,
        characteristics_json=json.dumps(segment.characteristics, default=str),
        channels=json.dumps(segment.recommended_channels, default=str),
        messaging_angle=segment.messaging_angle or "",
        visitor_profiles_json=json.dumps(visitor_profiles, indent=2, default=str),
        segment_id=str(segment.id),
        connected_accounts_info=accounts_info,
    )

    if not settings.anthropic_api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not configured — cannot plan campaign"
        )

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )
    first = message.content[0]
    if not isinstance(first, TextBlock):
        raise ValueError(f"Unexpected content block type: {type(first)}")
    plan = json.loads(first.text)

    campaign = Campaign(
        site_id=segment.site_id,
        segment_id=segment.id,
        name=plan.get("campaign_name", f"Campaign for {segment.name}"),
        status="draft",
        plan=plan,
    )
    db.add(campaign)
    await db.commit()

    logger.info("campaign_planned", segment_id=str(segment.id), campaign_id=str(campaign.id))
    return campaign


def _mock_campaign_plan(segment: Segment, profiles: list[dict]) -> dict:
    # Check if any profiles have social handles
    has_twitter = any(p.get("twitter_handle") for p in profiles)
    has_linkedin = any(p.get("linkedin_url") for p in profiles)

    touchpoints = [
        {
            "order": 1,
            "channel": "email",
            "delay_hours_from_start": 0,
            "subject": "Quick question about your visit, {{first_name}}",
            "body": (
                "Hi {{first_name}},\n\n"
                "I noticed you checked out our site recently. "
                "I'd love to understand what brought you there and if there's anything I can help with.\n\n"
                "Are you currently looking to solve {{pain_point}}?\n\n"
                "Happy to chat if you're interested.\n\n"
                "Best,\nThe Team"
            ),
            "personalization_fields": ["first_name", "pain_point"],
            "cta": "Reply to start a conversation",
        },
    ]

    order = 2
    if has_twitter:
        touchpoints.append({
            "order": order,
            "channel": "social_reply",
            "platform": "twitter",
            "delay_hours_from_start": 24,
            "reply_strategy": "conversational",
            "context": "Look for their recent tweets about industry topics and add thoughtful replies",
            "personalization_fields": ["first_name", "industry"],
        })
        order += 1

    if has_linkedin:
        touchpoints.append({
            "order": order,
            "channel": "linkedin",
            "delay_hours_from_start": 48,
            "connection_note": (
                "Hi {{first_name}}, I saw you're working on interesting things at {{company_name}}. "
                "Would love to connect!"
            ),
            "followup_message": (
                "Thanks for connecting! I noticed you visited our site. "
                "Happy to share some resources that might help with {{industry}} challenges."
            ),
            "personalization_fields": ["first_name", "company_name", "industry"],
        })
        order += 1

    touchpoints.append({
        "order": order,
        "channel": "meta_ads",
        "delay_hours_from_start": 0,
        "ad_headline": "Still exploring solutions?",
        "ad_body": "Join thousands of teams who already simplified their workflow. Start free today.",
        "audience_description": "Custom audience from email list of identified visitors in this segment",
    })

    return {
        "campaign_name": f"Re-engage {segment.name}",
        "segment_id": str(segment.id),
        "total_touchpoints": len(touchpoints),
        "touchpoints": touchpoints,
        "success_metric": "At least 1 email reply, 1 social engagement, or 2 LinkedIn connections within 7 days",
        "estimated_reach": f"~{len(profiles)} people via email + social, broader via paid ads",
    }
