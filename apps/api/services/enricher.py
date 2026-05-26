"""2-Tier enrichment service.

Tier 1 (PDL) — auto-runs after identity resolution. Provides: job title,
company, industry, LinkedIn URL, Twitter handle.

Tier 2 (Proxycurl + Twitter) — on-demand, uses user's BYOK API keys.
Provides: LinkedIn headline/summary/followers, Twitter bio/followers/topics.
"""

import random

import httpx
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.config import settings
from apps.api.models.api_key import UserApiKey
from apps.api.models.enrichment import EnrichmentProfile
from apps.api.models.visitor import IdentifiedVisitor, Visitor
from apps.api.services.key_vault import decrypt_key

logger = structlog.get_logger()

# Tier 1 fields (PDL) — max completeness = 0.6
TIER1_FIELDS: list[str] = [
    "job_title", "company_name", "industry",
    "linkedin_url", "twitter_handle",
]

# Tier 2 fields (Proxycurl + Twitter) — pushes completeness up to 1.0
TIER2_FIELDS: list[str] = [
    "linkedin_headline", "linkedin_summary",
    "twitter_bio", "twitter_follower_count",
]

ALL_ENRICHMENT_FIELDS = TIER1_FIELDS + TIER2_FIELDS


def calculate_completeness(profile: dict) -> float:
    """Calculate enrichment completeness as a fraction of all fields filled."""
    filled = sum(1 for f in ALL_ENRICHMENT_FIELDS if profile.get(f))
    return round(filled / len(ALL_ENRICHMENT_FIELDS), 2)


class Enricher:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ──────────────────────── Tier 1: PDL (auto) ────────────────────────

    async def enrich_tier1(
        self, visitor: Visitor, identified: IdentifiedVisitor
    ) -> EnrichmentProfile | None:
        """Run Tier 1 enrichment (PDL only). Auto-triggered after identity resolution."""
        if not identified.email:
            logger.info("enrichment_skipped_no_email", visitor_id=visitor.visitor_id[:8])
            return None

        pdl_data = await self._enrich_pdl(identified.email)
        if not pdl_data:
            visitor.enrichment_status = "failed"
            await self.db.commit()
            return None

        merged = {**pdl_data, "email": identified.email, "full_name": identified.full_name}
        completeness = calculate_completeness(merged)

        # Check if profile already exists (upsert)
        existing = await self._get_existing_profile(visitor)
        if existing:
            # Update existing profile with Tier 1 data
            for field in ["job_title", "company_name", "company_size", "industry",
                          "seniority_level", "linkedin_url", "twitter_handle",
                          "github_url", "personal_website"]:
                if pdl_data.get(field) is not None:
                    setattr(existing, field, pdl_data[field])
            existing.enrichment_completeness = completeness
            profile = existing
        else:
            profile = EnrichmentProfile(
                visitor_id=visitor.visitor_id,
                site_id=visitor.site_id,
                job_title=pdl_data.get("job_title"),
                company_name=pdl_data.get("company_name"),
                company_size=pdl_data.get("company_size"),
                industry=pdl_data.get("industry"),
                seniority_level=pdl_data.get("seniority_level"),
                linkedin_url=pdl_data.get("linkedin_url"),
                twitter_handle=pdl_data.get("twitter_handle"),
                github_url=pdl_data.get("github_url"),
                personal_website=pdl_data.get("personal_website"),
                enrichment_completeness=completeness,
            )
            self.db.add(profile)

        visitor.enrichment_status = "enriched" if completeness >= 0.3 else "partial"
        await self.db.commit()

        logger.info(
            "tier1_enriched",
            visitor_id=visitor.visitor_id[:8],
            completeness=completeness,
        )
        return profile

    # ──────────────────── Tier 2: BYOK (on-demand) ──────────────────────

    async def enrich_tier2(
        self,
        visitor: Visitor,
        user_id: str,
    ) -> EnrichmentProfile | None:
        """Run Tier 2 enrichment (Proxycurl + Twitter) using user's BYOK keys."""
        profile = await self._get_existing_profile(visitor)
        if not profile:
            logger.warning("tier2_no_tier1_profile", visitor_id=visitor.visitor_id[:8])
            return None

        # Fetch user's BYOK keys
        keys = await self._get_user_keys(user_id)
        if not keys:
            logger.info("tier2_no_keys", visitor_id=visitor.visitor_id[:8])
            return None

        updated = False

        # Proxycurl enrichment (if key available and LinkedIn URL exists)
        if "proxycurl" in keys and profile.linkedin_url:
            proxycurl_data = await self._enrich_proxycurl(
                profile.linkedin_url, api_key=keys["proxycurl"]
            )
            if proxycurl_data:
                profile.linkedin_headline = proxycurl_data.get("linkedin_headline")
                profile.linkedin_summary = proxycurl_data.get("linkedin_summary")
                profile.linkedin_follower_count = proxycurl_data.get("linkedin_follower_count")
                updated = True

        # Twitter enrichment (if key available and handle exists)
        if "twitter" in keys and profile.twitter_handle:
            twitter_data = await self._enrich_twitter(
                profile.twitter_handle, api_key=keys["twitter"]
            )
            if twitter_data:
                profile.twitter_bio = twitter_data.get("twitter_bio")
                profile.twitter_follower_count = twitter_data.get("twitter_follower_count")
                profile.twitter_recent_topics = twitter_data.get("twitter_recent_topics", [])
                updated = True

        if updated:
            # Recalculate completeness with all fields
            merged = {
                "job_title": profile.job_title,
                "company_name": profile.company_name,
                "industry": profile.industry,
                "linkedin_url": profile.linkedin_url,
                "twitter_handle": profile.twitter_handle,
                "linkedin_headline": profile.linkedin_headline,
                "linkedin_summary": profile.linkedin_summary,
                "twitter_bio": profile.twitter_bio,
                "twitter_follower_count": profile.twitter_follower_count,
            }
            profile.enrichment_completeness = calculate_completeness(merged)
            visitor.enrichment_status = "enriched"
            await self.db.commit()

            logger.info(
                "tier2_enriched",
                visitor_id=visitor.visitor_id[:8],
                completeness=profile.enrichment_completeness,
            )

        return profile

    # ──────────────────────── Helper methods ────────────────────────────

    async def _get_existing_profile(self, visitor: Visitor) -> EnrichmentProfile | None:
        result = await self.db.execute(
            select(EnrichmentProfile).where(
                EnrichmentProfile.site_id == visitor.site_id,
                EnrichmentProfile.visitor_id == visitor.visitor_id,
            )
        )
        return result.scalar_one_or_none()

    async def _get_user_keys(self, user_id: str) -> dict[str, str]:
        """Fetch and decrypt user's BYOK API keys. Returns {provider: plaintext_key}."""
        import uuid
        result = await self.db.execute(
            select(UserApiKey).where(
                UserApiKey.user_id == uuid.UUID(user_id),
                UserApiKey.is_valid == True,  # noqa: E712
            )
        )
        keys: dict[str, str] = {}
        for key_record in result.scalars().all():
            try:
                keys[key_record.provider] = decrypt_key(key_record.encrypted_key)
            except ValueError:
                logger.warning("byok_key_decrypt_failed", provider=key_record.provider)
        return keys

    # ──────────────────────── API Calls ──────────────────────────────────

    async def _enrich_pdl(self, email: str) -> dict | None:
        if settings.mock_external_apis:
            return self._mock_pdl_enrichment(email)

        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                resp = await client.get(
                    "https://api.peopledatalabs.com/v5/person/enrich",
                    headers={"X-Api-Key": settings.people_data_labs_api_key},
                    params={"email": email},
                )
                if resp.status_code == 200:
                    p = resp.json().get("data", {})
                    return {
                        "job_title": p.get("job_title"),
                        "company_name": p.get("job_company_name"),
                        "company_size": p.get("job_company_size"),
                        "industry": p.get("industry"),
                        "seniority_level": p.get("job_title_role"),
                        "linkedin_url": p.get("linkedin_url"),
                        "twitter_handle": (p.get("twitter_url", "") or "").rstrip("/").split("/")[-1] or None,
                        "github_url": p.get("github_url"),
                    }
            except httpx.HTTPError as e:
                logger.error("pdl_enrich_error", error=str(e))
        return None

    async def _enrich_proxycurl(self, linkedin_url: str, *, api_key: str) -> dict:
        if settings.mock_external_apis:
            return self._mock_proxycurl_enrichment()

        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                resp = await client.get(
                    "https://nubela.co/proxycurl/api/v2/linkedin",
                    headers={"Authorization": f"Bearer {api_key}"},
                    params={"url": linkedin_url},
                )
                if resp.status_code == 200:
                    p = resp.json()
                    return {
                        "linkedin_headline": p.get("headline"),
                        "linkedin_summary": p.get("summary"),
                        "linkedin_follower_count": p.get("follower_count"),
                    }
            except httpx.HTTPError as e:
                logger.error("proxycurl_error", error=str(e))
        return {}

    async def _enrich_twitter(self, handle: str, *, api_key: str) -> dict:
        if settings.mock_external_apis:
            return self._mock_twitter_enrichment()

        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                resp = await client.get(
                    f"https://api.twitter.com/2/users/by/username/{handle}",
                    headers={"Authorization": f"Bearer {api_key}"},
                    params={"user.fields": "description,public_metrics"},
                )
                if resp.status_code == 200:
                    u = resp.json().get("data", {})
                    return {
                        "twitter_bio": u.get("description"),
                        "twitter_follower_count": u.get("public_metrics", {}).get("followers_count"),
                    }
            except httpx.HTTPError as e:
                logger.error("twitter_error", error=str(e))
        return {}

    # ──────────────────────── Mock data ──────────────────────────────────

    def _mock_pdl_enrichment(self, email: str) -> dict:
        titles = ["CTO", "VP Engineering", "Product Manager", "Founder", "Growth Lead", "Software Engineer"]
        companies = ["TechStartup Inc", "ScaleAI Co", "CloudVenture", "DataDriven Labs", "IndieSaaS"]
        industries = ["Technology", "SaaS", "E-commerce", "FinTech", "HealthTech"]
        return {
            "job_title": random.choice(titles),
            "company_name": random.choice(companies),
            "company_size": random.choice(["1-10", "11-50", "51-200", "201-500"]),
            "industry": random.choice(industries),
            "seniority_level": random.choice(["senior", "executive", "manager", "entry"]),
            "linkedin_url": f"https://linkedin.com/in/{email.split('@')[0]}",
            "twitter_handle": email.split("@")[0].replace(".", ""),
            "github_url": f"https://github.com/{email.split('@')[0].replace('.', '')}" if random.random() > 0.5 else None,
        }

    def _mock_proxycurl_enrichment(self) -> dict:
        headlines = [
            "Building the future of SaaS",
            "Engineering Leader | Startup Advisor",
            "Product-led growth enthusiast",
            "Full-stack developer & indie maker",
        ]
        return {
            "linkedin_headline": random.choice(headlines),
            "linkedin_summary": "Passionate about building products that solve real problems.",
            "linkedin_follower_count": random.randint(200, 5000),
        }

    def _mock_twitter_enrichment(self) -> dict:
        bios = [
            "Building stuff. Shipping fast.",
            "Founder @startup. Ex-FAANG.",
            "Product & growth. DMs open.",
            "Code, coffee, startups.",
        ]
        return {
            "twitter_bio": random.choice(bios),
            "twitter_follower_count": random.randint(100, 10000),
            "twitter_recent_topics": random.sample(
                ["AI", "startups", "SaaS", "growth", "coding", "product"], 3
            ),
        }

    # ──────────────────────── Legacy compat ──────────────────────────────

    async def enrich(self, visitor: Visitor, identified: IdentifiedVisitor) -> EnrichmentProfile | None:
        """Legacy method — calls tier1 only. Used by resolution_tasks.py."""
        return await self.enrich_tier1(visitor, identified)
