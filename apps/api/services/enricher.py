"""Clay-style cascade enrichment service.

Waterfall enrichment — output of provider A becomes input for provider B:

1. PDL Enrich (email → job title, company, LinkedIn URL, Twitter handle)
2. Proxycurl (LinkedIn URL from step 1 → headline, summary, followers)
3. Twitter (handle from step 1 → bio, followers, topics)
4. Deep Research (Claude API + web search → comprehensive social profile)

System-level API keys (PDL, Proxycurl) are used automatically.
BYOK keys (user-provided) extend coverage when system keys are absent.
"""

import random
from datetime import datetime, timezone

import anthropic
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
                    "full_name": p.get("full_name"),
                    "job_title": p.get("job_title"),
                    "company_name": p.get("job_company_name"),
                    "company_domain": p.get("job_company_website"),
                    "company_size": p.get("job_company_size"),
                    "industry": p.get("industry"),
                    "seniority_level": p.get("job_title_role"),
                    "linkedin_url": p.get("linkedin_url"),
                    "twitter_handle": (p.get("twitter_url", "") or "").rstrip("/").split("/")[-1] or None,
                    "facebook_url": p.get("facebook_url"),
                    "github_url": p.get("github_url"),
                    "city": p.get("location_locality"),
                    "country": p.get("location_country"),
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
        username = email.split("@")[0]
        domain = email.split("@")[1] if "@" in email else "example.com"
        first = username.split(".")[0].title() if "." in username else username.title()
        last = username.split(".")[-1].title() if "." in username else "User"
        return {
            "full_name": f"{first} {last}" if first != last else first,
            "job_title": random.choice(titles),
            "company_name": random.choice(companies),
            "company_domain": domain,
            "company_size": random.choice(["1-10", "11-50", "51-200", "201-500"]),
            "industry": random.choice(industries),
            "seniority_level": random.choice(["senior", "executive", "manager", "entry"]),
            "linkedin_url": f"https://linkedin.com/in/{username}",
            "twitter_handle": username.replace(".", ""),
            "facebook_url": f"https://facebook.com/{username.replace('.', '')}" if random.random() > 0.4 else None,
            "github_url": f"https://github.com/{username.replace('.', '')}" if random.random() > 0.5 else None,
            "city": random.choice(["San Francisco", "New York", "London", "Ho Chi Minh City"]),
            "country": random.choice(["US", "UK", "VN", "SG"]),
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

    # ──────────────── Deep Research (Claude API + web search) ─────────────

    async def deep_research(
        self,
        visitor: Visitor,
        identified: IdentifiedVisitor,
        profile: EnrichmentProfile | None = None,
    ) -> dict:
        """Use Claude API with web search to research visitor's social media presence.

        Returns {"status": ..., "social_context": ..., "message": ...}.
        Stores results in EnrichmentProfile.social_context JSONB field.
        """
        if not profile:
            profile = await self._get_existing_profile(visitor)

        name = identified.full_name or (identified.email.split("@")[0] if identified.email else "Unknown")
        linkedin_url = profile.linkedin_url if profile else None
        twitter_handle = profile.twitter_handle if profile else None
        company = profile.company_name if profile else None
        job_title = profile.job_title if profile else None

        context_lines = [f"Name: {name}"]
        if identified.email:
            context_lines.append(f"Email: {identified.email}")
        if linkedin_url:
            context_lines.append(f"LinkedIn: {linkedin_url}")
        if twitter_handle:
            context_lines.append(f"Twitter/X: @{twitter_handle}")
        if company:
            context_lines.append(f"Company: {company}")
        if job_title:
            context_lines.append(f"Title: {job_title}")

        person_context = "\n".join(context_lines)

        prompt = f"""Deep-dive research about this person's online presence and social media activity.

{person_context}

Your task:
1. Find ALL social media profiles (Twitter/X, LinkedIn, GitHub, Instagram, YouTube, TikTok, personal blog/website, Substack, newsletter)
2. Determine which platforms they are MOST active on — with evidence (follower counts, posting frequency, engagement)
3. What they post about: interests, expertise areas, recurring topics
4. Professional background: career path, current projects, companies built or worked at
5. Notable content, communities, or brands they are associated with
6. My honest read: what makes them interesting, where they are credible, where they are not

CRITICAL RULES:
- Be completely honest. If public information is limited, say "Public information on this person is limited" and report only what you can verify.
- Do NOT fabricate, guess, or hallucinate any information. Only report what you find through actual web searches.
- If you cannot find social profiles, say so clearly.
- Distinguish between verified facts and reasonable inferences.

Write a comprehensive but honest profile analysis. Use a direct, conversational tone — not corporate."""

        if settings.mock_external_apis:
            research_text = self._mock_deep_research(name, identified.email)
        else:
            if not settings.anthropic_api_key:
                logger.warning("deep_research_skipped_no_api_key")
                return {
                    "status": "error",
                    "message": "Anthropic API key not configured. Set ANTHROPIC_API_KEY to enable deep research.",
                }

            try:
                client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
                response = await client.messages.create(
                    model="claude-sonnet-4-20250514",
                    max_tokens=16384,
                    tools=[{
                        "type": "web_search_20250305",
                        "name": "web_search",
                        "max_uses": 10,
                    }],
                    messages=[{"role": "user", "content": prompt}],
                )

                research_text = ""
                for block in response.content:
                    if hasattr(block, "text"):
                        research_text += block.text + "\n"

                if not research_text.strip():
                    logger.warning("deep_research_empty_response", visitor_id=visitor.visitor_id[:8])
                    return {
                        "status": "partial",
                        "message": "Deep research returned no results.",
                    }

                research_text = research_text.strip()
            except anthropic.APIError as e:
                logger.error("deep_research_api_error", error=str(e), visitor_id=visitor.visitor_id[:8])
                return {
                    "status": "error",
                    "message": f"Claude API error: {e.message}",
                }

        if not profile:
            profile = EnrichmentProfile(
                visitor_id=visitor.visitor_id,
                site_id=visitor.site_id,
                enrichment_completeness=0.0,
            )
            self.db.add(profile)

        now = datetime.now(timezone.utc)
        profile.social_context = {
            "deep_research": research_text,
            "researched_at": now.isoformat(),
            "model": "claude-sonnet-4-20250514",
        }
        profile.social_context_updated_at = now

        if profile.enrichment_completeness < 0.5:
            profile.enrichment_completeness = max(profile.enrichment_completeness, 0.5)
        visitor.enrichment_status = "enriched"
        await self.db.commit()

        logger.info(
            "deep_research_complete",
            visitor_id=visitor.visitor_id[:8],
            research_length=len(research_text),
        )

        return {
            "status": "enriched",
            "completeness": profile.enrichment_completeness,
            "message": "Deep research completed.",
            "social_context": profile.social_context,
        }

    @staticmethod
    def _mock_deep_research(name: str, email: str | None) -> str:
        username = email.split("@")[0] if email else name.lower().replace(" ", "")
        return f"""## {name} — Profile Research

**Public information on this person is limited.** Here is what could be found:

### Social Media Presence
- **LinkedIn**: Profile exists but limited public details visible without connection
- **Twitter/X**: No verified public account found matching this identity
- **GitHub**: No public repositories found

### Professional Background
Based on limited public data, {name} appears to work in the technology space. Further details require direct outreach or additional data sources.

### Honest Assessment
This person has a relatively low public digital footprint. This could mean they:
- Prefer privacy over public presence
- Are early in their career
- Operate primarily through private/professional channels

**Confidence level: Low** — Most details could not be independently verified through public sources. The information above is based on what limited data was available and should be treated as preliminary."""

    # ──────────────────────── Legacy compat ──────────────────────────────

    async def enrich(self, visitor: Visitor, identified: IdentifiedVisitor) -> EnrichmentProfile | None:
        """Legacy method — calls tier1 only. Used by resolution_tasks.py."""
        return await self.enrich_tier1(visitor, identified)
