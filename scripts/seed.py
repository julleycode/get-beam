"""Seed test data into PostgreSQL and ClickHouse."""
import asyncio
import random
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from apps.api.models.database import async_session, engine, Base
from apps.api.models.user import User
from apps.api.models.site import Site
from apps.api.models.visitor import Visitor, IdentifiedVisitor
from apps.api.models.enrichment import EnrichmentProfile
from apps.api.models.segment import Segment, SegmentMember
from apps.api.models.campaign import Campaign
from apps.api.models.social_account import SocialAccount  # noqa: F401
from apps.api.models.company import Company  # noqa: F401
from apps.api.models.beam_identity import BeamIdentityNode  # noqa: F401
from apps.api.models.draft import Draft  # noqa: F401
from apps.api.models.post import Post  # noqa: F401
from apps.api.models.api_key import *  # noqa: F401,F403
from apps.api.models.engagement_attribution import *  # noqa: F401,F403
from apps.api.models.event import *  # noqa: F401,F403
from apps.api.models.feature_request import *  # noqa: F401,F403
from apps.api.models.message import *  # noqa: F401,F403
from apps.api.models.visitor_email import *  # noqa: F401,F403
from apps.api.models.voice_example import *  # noqa: F401,F403
from apps.api.models.waitlist import *  # noqa: F401,F403
from apps.api.services.auth import hash_password
from apps.api.services.clickhouse_client import init_clickhouse_schema, get_clickhouse_client
from apps.api.services.visitor_aggregator import calculate_intent_score


async def seed() -> None:
    # Create tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    init_clickhouse_schema()

    async with async_session() as db:
        # Create test user
        user = User(
            email="demo@getbeam.fyi",
            hashed_password=hash_password("password123"),
            full_name="Demo User",
        )
        db.add(user)
        await db.flush()

        # Create test site
        site = Site(
            site_id="site_demo123456",
            user_id=user.id,
            name="Demo SaaS App",
            url="https://demo.example.com",
            description="A project management tool for remote teams",
            category="SaaS",
        )
        db.add(site)
        await db.flush()

        # Create visitors with varying intent
        now = datetime.utcnow()
        first_names = ["John", "Sarah", "Mike", "Emma", "Alex", "Lisa", "David", "Rachel",
                       "Tom", "Anna", "Chris", "Megan", "James", "Olivia", "Ryan", "Kate"]
        last_names = ["Smith", "Johnson", "Williams", "Brown", "Jones", "Davis", "Miller", "Wilson"]
        titles = ["CTO", "VP Engineering", "Product Manager", "Founder", "Growth Lead",
                  "Software Engineer", "Head of Product", "CEO"]
        companies = ["TechStartup Inc", "ScaleAI Co", "CloudVenture", "DataDriven Labs",
                     "IndieSaaS", "BuildFast Corp", "ShipIt HQ"]
        industries = ["Technology", "SaaS", "E-commerce", "FinTech", "HealthTech", "EdTech"]
        pages = ["/", "/pricing", "/features", "/about", "/blog", "/demo", "/contact",
                 "/signup", "/docs", "/changelog"]

        visitors_data = []
        for i in range(25):
            vid = str(uuid.uuid4())
            hours_ago = random.randint(1, 168)
            sessions = random.randint(1, 5)
            pvs = random.randint(1, 20)
            scroll = random.choice([25, 50, 75, 100])
            time_on_page = random.uniform(10, 120)
            visited = random.sample(pages, random.randint(1, 5))

            intent = calculate_intent_score(
                last_seen=now - timedelta(hours=hours_ago),
                total_sessions=sessions,
                max_scroll_depth=scroll,
                avg_time_on_page=time_on_page,
                pages_visited=visited,
            )

            visitor = Visitor(
                site_id=site.site_id,
                visitor_id=vid,
                first_seen=now - timedelta(hours=hours_ago + 24),
                last_seen=now - timedelta(hours=hours_ago),
                total_pageviews=pvs,
                total_sessions=sessions,
                avg_time_on_page=time_on_page,
                max_scroll_depth=scroll,
                pages_visited=visited,
                top_referrer=random.choice(["google.com", "twitter.com", "linkedin.com", None]),
                utm_source=random.choice(["google", "twitter", None]),
                country_code="US",
                device_type=random.choice(["desktop", "mobile", "tablet"]),
                intent_score=intent,
                identity_status="anonymous",
                enrichment_status="pending",
            )
            db.add(visitor)
            visitors_data.append((visitor, vid, intent))

        await db.flush()

        # Identify and enrich some visitors
        for visitor, vid, intent in visitors_data[:12]:
            fn = random.choice(first_names)
            ln = random.choice(last_names)

            identified = IdentifiedVisitor(
                visitor_id=vid,
                site_id=site.site_id,
                email=f"{fn.lower()}.{ln.lower()}@example.com",
                full_name=f"{fn} {ln}",
                city=random.choice(["San Francisco", "New York", "Austin", "Seattle"]),
                region=random.choice(["CA", "NY", "TX", "WA"]),
                country="US",
                resolution_provider="people_data_labs",
                confidence_score=round(random.uniform(0.5, 0.95), 2),
            )
            db.add(identified)
            visitor.identity_status = "identified"

            title = random.choice(titles)
            company = random.choice(companies)
            industry = random.choice(industries)

            profile = EnrichmentProfile(
                visitor_id=vid,
                site_id=site.site_id,
                job_title=title,
                company_name=company,
                company_size=random.choice(["1-10", "11-50", "51-200"]),
                industry=industry,
                seniority_level=random.choice(["senior", "executive", "manager"]),
                linkedin_url=f"https://linkedin.com/in/{fn.lower()}{ln.lower()}",
                twitter_handle=f"{fn.lower()}{ln.lower()}",
                linkedin_headline=f"{title} at {company}",
                enrichment_completeness=round(random.uniform(0.5, 1.0), 2),
            )
            db.add(profile)
            visitor.enrichment_status = "enriched"

        await db.flush()

        # Create a segment
        segment = Segment(
            site_id=site.site_id,
            name="High-Intent Evaluators",
            description="Technical leaders actively evaluating the product",
            characteristics={
                "common_job_titles": ["CTO", "VP Engineering", "Founder"],
                "common_industries": ["Technology", "SaaS"],
                "avg_intent_score": 72,
            },
            recommended_channels=["email", "linkedin"],
            messaging_angle="Direct value proposition with social proof",
            priority="high",
            visitor_count=8,
        )
        db.add(segment)
        await db.flush()

        for visitor, vid, intent in visitors_data[:8]:
            db.add(SegmentMember(
                segment_id=segment.id,
                visitor_id=vid,
                site_id=site.site_id,
            ))

        # Create a campaign
        campaign = Campaign(
            site_id=site.site_id,
            segment_id=segment.id,
            name="Re-engage High-Intent Evaluators",
            status="draft",
            plan={
                "campaign_name": "Re-engage High-Intent Evaluators",
                "total_touchpoints": 3,
                "touchpoints": [
                    {
                        "order": 1,
                        "channel": "email",
                        "delay_hours_from_start": 0,
                        "subject": "Quick question about your visit, {{first_name}}",
                        "body": "Hi {{first_name}},\n\nI noticed you were checking out our platform. As {{job_title}} at {{company_name}}, you might find our features interesting.\n\nWould love to chat!\n\nBest,\nThe Team",
                        "cta": "Reply to start a conversation",
                    },
                    {
                        "order": 2,
                        "channel": "linkedin",
                        "delay_hours_from_start": 48,
                        "connection_note": "Hi {{first_name}}, fellow {{industry}} enthusiast here. Would love to connect!",
                        "followup_message": "Thanks for connecting! Happy to share resources.",
                    },
                    {
                        "order": 3,
                        "channel": "meta_ads",
                        "delay_hours_from_start": 0,
                        "ad_headline": "Still exploring solutions?",
                        "ad_body": "Join thousands of teams. Start free today.",
                    },
                ],
            },
        )
        db.add(campaign)

        await db.commit()
        print("Seed data created successfully!")
        print(f"  User: demo@getbeam.fyi / password123")
        print(f"  Site: {site.site_id}")
        print(f"  Visitors: 25 (12 identified & enriched)")
        print(f"  Segments: 1")
        print(f"  Campaigns: 1 (draft)")


if __name__ == "__main__":
    asyncio.run(seed())
