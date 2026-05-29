"""Clay-style cascade enrichment service.

Waterfall enrichment — output of provider A becomes input for provider B:

1. PDL Enrich (email → job title, company, LinkedIn URL, Twitter handle)
2. Proxycurl (LinkedIn URL from step 1 → headline, summary, followers)
3. Twitter (handle from step 1 → bio, followers, topics)

System-level API keys (PDL, Proxycurl) are used automatically.
BYOK keys (user-provided) extend coverage when system keys are absent.
"""

import random

import httpx
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception

from apps.api.config import settings
from apps.api.models.api_key import UserApiKey
from apps.api.models.enrichment import EnrichmentProfile
from apps.api.models.visitor import IdentifiedVisitor, Visitor
from apps.api.services.key_vault import decrypt_key

logger = structlog.get_logger()

# Transient HTTP statuses worth retrying
_TRANSIENT_HTTP_STATUSES = {429, 500, 502, 503, 504}


def _is_transient_http_error(exc: BaseException) -> bool:
    """Return True for retryable httpx errors (timeouts, connection errors, 5xx/429)."""
    if isinstance(exc, httpx.TimeoutException):
        return True
    if isinstance(exc, httpx.ConnectError):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in _TRANSIENT_HTTP_STATUSES
    return False


# Retry decorator: 3 attempts, exponential backoff 1→2→8s, transient errors only.
_http_retry = retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    retry=retry_if_exception(_is_transient_http_error),
    reraise=True,
)


# All enrichment fields — used for completeness scoring
ENRICHMENT_FIELDS: list[str] = [
    "job_title", "company_name", "industry",
    "linkedin_url", "twitter_handle", "facebook_url",
    "linkedin_headline", "linkedin_summary",
    "twitter_bio", "twitter_follower_count",
]


def calculate_completeness(profile: dict) -> float:
    """Calculate enrichment completeness as a fraction of all fields filled."""
    filled = sum(1 for f in ENRICHMENT_FIELDS if profile.get(f))
    return round(filled / len(ENRICHMENT_FIELDS), 2)


class Enricher:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ──────────────── Cascade Enrichment (Clay-style) ─────────────────

    async def enrich_tier1(
        self, visitor: Visitor, identified: IdentifiedVisitor
    ) -> EnrichmentProfile | None:
        """Run full cascade enrichment after identity resolution.

        Clay-style waterfall:
        1. PDL Enrich (email → professional data + social URLs)
        2. Proxycurl (linkedin_url from step 1 → headline, summary, followers)
        3. Twitter (handle from step 1 → bio, followers, topics)

        Uses system API keys first, falls back to BYOK if available.
        """
        if not identified.email:
            logger.info("enrichment_skipped_no_email", visitor_id=visitor.visitor_id[:8])
            return None

        # ── Step 1: PDL Enrich (email → professional data) ──
        pdl_data = await self._enrich_pdl(identified.email)
        if not pdl_data:
            visitor.enrichment_status = "failed"
            await self.db.commit()
            return None

        # Upsert enrichment profile with PDL data
        profile = await self._upsert_profile(visitor, pdl_data)

        # ── Step 2: Cascade — Proxycurl (linkedin_url → details) ──
        linkedin_url = pdl_data.get("linkedin_url") or (profile.linkedin_url if profile else None)
        if linkedin_url:
            proxycurl_key = self._get_system_proxycurl_key()
            if proxycurl_key:
                proxycurl_data = await self._enrich_proxycurl(linkedin_url, api_key=proxycurl_key)
                if proxycurl_data:
                    profile.linkedin_headline = proxycurl_data.get("linkedin_headline")
                    profile.linkedin_summary = proxycurl_data.get("linkedin_summary")
                    profile.linkedin_follower_count = proxycurl_data.get("linkedin_follower_count")
                    logger.info("cascade_proxycurl_ok", visitor_id=visitor.visitor_id[:8])

        # ── Step 3: Cascade — Twitter (handle → bio/followers) ──
        twitter_handle = pdl_data.get("twitter_handle") or (profile.twitter_handle if profile else None)
        if twitter_handle:
            twitter_key = self._get_system_twitter_key()
            if twitter_key:
                twitter_data = await self._enrich_twitter(twitter_handle, api_key=twitter_key)
                if twitter_data:
                    profile.twitter_bio = twitter_data.get("twitter_bio")
                    profile.twitter_follower_count = twitter_data.get("twitter_follower_count")
                    profile.twitter_recent_topics = twitter_data.get("twitter_recent_topics", [])
                    logger.info("cascade_twitter_ok", visitor_id=visitor.visitor_id[:8])

        # ── Final: recalculate completeness with all cascade data ──
        completeness = self._profile_completeness(profile)
        profile.enrichment_completeness = completeness
        visitor.enrichment_status = "enriched" if completeness >= 0.3 else "partial"
        await self.db.commit()

        logger.info(
            "cascade_enrichment_complete",
            visitor_id=visitor.visitor_id[:8],
            completeness=completeness,
            has_linkedin=bool(profile.linkedin_headline),
            has_twitter=bool(profile.twitter_bio),
        )
        return profile

    # ──────────────────── Tier 2: BYOK (on-demand) ──────────────────────

    async def enrich_tier2(
        self,
        visitor: Visitor,
        user_id: str,
    ) -> EnrichmentProfile | None:
        """Run BYOK enrichment using user's own API keys.

        Fills gaps left by cascade enrichment (e.g. if system has no
        Proxycurl key, user can provide their own).
        """
        profile = await self._get_existing_profile(visitor)
        if not profile:
            logger.warning("tier2_no_profile", visitor_id=visitor.visitor_id[:8])
            return None

        # Fetch user's BYOK keys
        keys = await self._get_user_keys(user_id)
        if not keys:
            logger.info("tier2_no_keys", visitor_id=visitor.visitor_id[:8])
            return None

        updated = False

        # Proxycurl (fill if cascade didn't run or returned nothing)
        if "proxycurl" in keys and profile.linkedin_url and not profile.linkedin_headline:
            proxycurl_data = await self._enrich_proxycurl(
                profile.linkedin_url, api_key=keys["proxycurl"]
            )
            if proxycurl_data:
                profile.linkedin_headline = proxycurl_data.get("linkedin_headline")
                profile.linkedin_summary = proxycurl_data.get("linkedin_summary")
                profile.linkedin_follower_count = proxycurl_data.get("linkedin_follower_count")
                updated = True

        # Twitter (fill if cascade didn't run or returned nothing)
        if "twitter" in keys and profile.twitter_handle and not profile.twitter_bio:
            twitter_data = await self._enrich_twitter(
                profile.twitter_handle, api_key=keys["twitter"]
            )
            if twitter_data:
                profile.twitter_bio = twitter_data.get("twitter_bio")
                profile.twitter_follower_count = twitter_data.get("twitter_follower_count")
                profile.twitter_recent_topics = twitter_data.get("twitter_recent_topics", [])
                updated = True

        if updated:
            profile.enrichment_completeness = self._profile_completeness(profile)
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

    async def _upsert_profile(
        self, visitor: Visitor, pdl_data: dict
    ) -> EnrichmentProfile:
        """Create or update enrichment profile with PDL data."""
        existing = await self._get_existing_profile(visitor)
        pdl_fields = [
            "job_title", "company_name", "company_size", "industry",
            "seniority_level", "linkedin_url", "twitter_handle",
            "facebook_url", "github_url", "personal_website",
        ]
        if existing:
            for field in pdl_fields:
                val = pdl_data.get(field)
                if val is not None:
                    setattr(existing, field, val)
            return existing

        profile = EnrichmentProfile(
            visitor_id=visitor.visitor_id,
            site_id=visitor.site_id,
            **{f: pdl_data.get(f) for f in pdl_fields},
            enrichment_completeness=0.0,
        )
        self.db.add(profile)
        return profile

    def _profile_completeness(self, profile: EnrichmentProfile) -> float:
        """Calculate completeness from a live profile object."""
        filled = sum(1 for f in ENRICHMENT_FIELDS if getattr(profile, f, None))
        return round(filled / len(ENRICHMENT_FIELDS), 2)

    @staticmethod
    def _get_system_proxycurl_key() -> str | None:
        """Return system-level Proxycurl API key (if configured)."""
        key = settings.proxycurl_api_key
        return key if key else None

    @staticmethod
    def _get_system_twitter_key() -> str | None:
        """Return system-level Twitter bearer token (if configured)."""
        key = settings.twitter_bearer_token
        return key if key else None

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

    @_http_retry
    async def _enrich_pdl(self, email: str) -> dict | None:
        """Enrich a person record from PDL by email.

        Guards for missing API key (returns None immediately — does not attempt
        a call with an empty key which would mark the visitor permanently failed).
        Retries up to 3× on transient errors (5xx, 429, timeouts).
        """
        if not settings.people_data_labs_api_key:
            # No key configured — skip silently rather than sending an empty key
            logger.debug("pdl_enrich_skipped_no_key")
            return None

        if settings.mock_external_apis:
            return self._mock_pdl_enrichment(email)

        async with httpx.AsyncClient(timeout=10.0) as client:
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
                    "facebook_url": p.get("facebook_url"),
                    "github_url": p.get("github_url"),
                }
            elif resp.status_code == 404:
                logger.debug("pdl_enrich_no_match", email_prefix=email[:5])
            else:
                logger.warning("pdl_enrich_error", status=resp.status_code)
                if resp.status_code in _TRANSIENT_HTTP_STATUSES:
                    resp.raise_for_status()
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
            "facebook_url": f"https://facebook.com/{email.split('@')[0].replace('.', '')}" if random.random() > 0.4 else None,
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
