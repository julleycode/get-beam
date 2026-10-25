"""Clay-style cascade enrichment service.

Waterfall enrichment — output of provider A becomes input for provider B:

1. PDL Enrich (email → job title, company, LinkedIn URL, Twitter handle)
   1b. Apollo people/match — fallback when PDL has no record for the address
   1c. Email domain → company name/domain — free last resort, no job title
2. Proxycurl (LinkedIn URL from step 1 → headline, summary, followers)
3. Twitter (handle from step 1 → bio, followers, topics)
4. Deep Research (Claude API + web search → comprehensive social profile)

Steps 2-4 consume step 1's OUTPUT, so a step-1 miss used to mean zero
enrichment for that visitor — and PDL, a US-centric B2B dataset, misses most
non-US and small-company addresses. Steps 1b/1c exist to keep the waterfall
producing something in that (common) case. Consumer mailboxes deliberately get
nothing from 1c: an employer cannot be inferred from gmail.com.

System-level API keys (PDL, Apollo, Proxycurl) are used automatically.
BYOK keys (user-provided) extend coverage when system keys are absent.
"""

import hashlib
import json as jsonlib
from datetime import datetime, timezone

import httpx
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception

from apps.api.config import settings
from apps.api.models.api_key import UserApiKey
from apps.api.models.enrichment import EnrichmentProfile
from apps.api.models.visitor import IdentifiedVisitor, Visitor
from apps.api.services.gemini_client import GeminiError, gemini_generate
from apps.api.services.key_vault import decrypt_key
from apps.api.services.redis_client import get_redis
from apps.api.services.usage_logger import log_api_call

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


# Consumer mailbox providers. An address here says nothing about an employer,
# so the domain fallback must not invent a company from it (a "Gmail" company
# on a lead is worse than an empty field).
_FREE_MAIL_DOMAINS: frozenset[str] = frozenset({
    "gmail.com", "googlemail.com", "yahoo.com", "yahoo.co.uk", "yahoo.co.jp",
    "hotmail.com", "hotmail.co.uk", "outlook.com", "live.com", "msn.com",
    "aol.com", "icloud.com", "me.com", "mac.com", "proton.me", "protonmail.com",
    "gmx.com", "gmx.de", "mail.com", "zoho.com", "yandex.com", "yandex.ru",
    "qq.com", "163.com", "126.com", "naver.com", "hanmail.net", "daum.net",
    "fastmail.com", "hey.com", "tutanota.com", "pm.me", "duck.com",
})


def _domain_enrichment(email: str | None) -> dict | None:
    """Last-resort, zero-cost enrichment: company identity from the email domain.

    Returns None for consumer mailboxes and malformed addresses. This yields
    only ``company_name``/``company_domain`` — deliberately no job title, since
    a domain says where someone works, never what they do.
    """
    if not email or "@" not in email:
        return None
    domain = email.rsplit("@", 1)[1].strip().lower().lstrip("www.")
    if not domain or "." not in domain or domain in _FREE_MAIL_DOMAINS:
        return None
    # "acme-corp.co.uk" → "Acme Corp"; the registrable label only.
    label = domain.split(".")[0]
    company = label.replace("-", " ").replace("_", " ").strip().title()
    if not company:
        return None
    return {"company_name": company, "company_domain": domain}


# All enrichment fields — used for completeness scoring
ENRICHMENT_FIELDS: list[str] = [
    "job_title", "company_name", "industry",
    "linkedin_url", "twitter_handle", "facebook_url",
    "linkedin_headline", "linkedin_summary",
    "twitter_bio", "twitter_follower_count",
]


# Business rule: cache enrichment API results for 7 days (cost control —
# the same email re-identified under another visitor/site must not re-pay
# PDL/Proxycurl/Twitter). Misses are negative-cached too: a known-missing
# person costs as much to re-query as a hit.
ENRICH_CACHE_TTL_SECONDS = 7 * 86400
_CACHE_MISS_MARKER = "__no_match__"


class _PDLNonTransientError(Exception):
    """PDL returned a non-transient, non-404 error (e.g. 401 bad key, 400).
    NOT a definitive no-match — the caller must leave the visitor retryable."""


def _apply_proxycurl(profile, proxycurl_data: dict) -> None:
    """Copy Proxycurl fields onto the profile. Never clobber an existing value
    with a null/missing key — a partial 200 response must not wipe good data."""
    if (v := proxycurl_data.get("linkedin_headline")) is not None:
        profile.linkedin_headline = v
    if (v := proxycurl_data.get("linkedin_summary")) is not None:
        profile.linkedin_summary = v
    if (v := proxycurl_data.get("linkedin_follower_count")) is not None:
        profile.linkedin_follower_count = v


def _apply_twitter(profile, twitter_data: dict) -> None:
    """Copy Twitter fields onto the profile. Never clobber existing values with
    nulls; topics are populate-only (a fresh empty response won't wipe prior)."""
    if (v := twitter_data.get("twitter_bio")) is not None:
        profile.twitter_bio = v
    if (v := twitter_data.get("twitter_follower_count")) is not None:
        profile.twitter_follower_count = v
    if topics := twitter_data.get("twitter_recent_topics"):
        profile.twitter_recent_topics = topics
    if (v := twitter_data.get("avatar_url")) is not None:
        profile.avatar_url = v


def _upgrade_twitter_avatar(url: str | None) -> str | None:
    """Twitter/X returns a 48px avatar (``_normal.`` suffix); upgrade to 400px.
    Safe no-op for URLs without the marker (e.g. OSINT images)."""
    if not url:
        return None
    return url.replace("_normal.", "_400x400.")


def _avatar_from_social_context(social_context: dict | None) -> str | None:
    """Return the first usable avatar URL from OSINT profiles in social_context.
    Secondary source only (Twitter/X is primary). None when nothing is found."""
    if not isinstance(social_context, dict):
        return None
    res = social_context.get("social_resolution")
    if not isinstance(res, dict):
        return None
    for account in (res.get("profiles") or []):
        extra = account.get("extra") if isinstance(account, dict) else None
        if not isinstance(extra, dict):
            continue
        for key in ("avatar", "profile_pic", "picture"):
            val = extra.get(key)
            if isinstance(val, str) and val.startswith("http"):
                return val
    return None


class Enricher:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ──────────────────── Redis result cache (7-day TTL) ────────────────

    @staticmethod
    async def _cache_get(key: str) -> tuple[bool, dict | None]:
        """(hit, data) — data is None on a negative-cache hit.
        Redis failures degrade to a miss; caching is best-effort."""
        try:
            raw = await get_redis().get(key)
        except Exception:
            return (False, None)
        if raw is None:
            return (False, None)
        if raw == _CACHE_MISS_MARKER:
            return (True, None)
        try:
            return (True, jsonlib.loads(raw))
        except (ValueError, TypeError):
            return (False, None)

    @staticmethod
    async def _cache_set(key: str, data: dict | None) -> None:
        try:
            raw = _CACHE_MISS_MARKER if data is None else jsonlib.dumps(data, default=str)
            await get_redis().set(key, raw, ex=ENRICH_CACHE_TTL_SECONDS)
        except Exception:
            logger.debug("enrich_cache_set_failed", key=key)

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

        # Known-contact routing: if this email is already in the customer's CRM
        # list, they own its data — skip the paid enrichment waterfall entirely.
        if settings.skip_enrich_known:
            from apps.api.services.known_contacts_match import is_known_contact

            known, source = await is_known_contact(
                self.db, visitor.site_id, identified.email
            )
            if known:
                logger.info(
                    "enrichment_skipped_known_contact",
                    visitor_id=visitor.visitor_id[:8],
                    source=source,
                )
                visitor.enrichment_status = "skipped_known"
                await self.db.commit()
                return None

        # Missing PDL key: leave the visitor's enrichment status untouched so
        # the visitor stays retryable once the key is configured. Calling the
        # API with an empty key 401s and used to mark everyone permanently
        # "failed" on key-less deploys.
        if not settings.people_data_labs_api_key:
            logger.warning(
                "enrichment_unavailable_no_pdl_key",
                visitor_id=visitor.visitor_id[:8],
            )
            return None

        # ── Step 1: PDL Enrich (email → professional data) ──
        # A transient PDL failure (timeout/5xx after retries) raises out of
        # here and the caller leaves the status retryable; only a definitive
        # no-match marks "failed".
        try:
            person_data = await self._enrich_pdl(identified.email, visitor=visitor)
        except _PDLNonTransientError:
            # Bad/expired PDL key (or 400): leave the visitor retryable instead
            # of marking it permanently "failed" on a key problem.
            logger.warning("enrichment_pdl_non_transient_retryable", visitor_id=visitor.visitor_id[:8])
            return None

        # ── Step 1b: PDL missed → Apollo person-match ──
        # PDL is a US-centric B2B dataset, so it 404s on most non-US and
        # small-company addresses. Before this fallback existed a PDL miss meant
        # zero enrichment: steps 2 and 3 below consume PDL's own output, so they
        # cannot run without it.
        if not person_data:
            person_data = await self._enrich_apollo(identified.email, visitor=visitor)

        # ── Step 1c: both people-providers missed → free company-from-domain ──
        if not person_data:
            person_data = _domain_enrichment(identified.email)
            if person_data:
                logger.info(
                    "enrichment_domain_fallback",
                    visitor_id=visitor.visitor_id[:8],
                    company_domain=person_data.get("company_domain"),
                )

        if not person_data:
            visitor.enrichment_status = "failed"
            await self.db.commit()
            return None

        # Upsert enrichment profile with whichever provider matched
        profile = await self._upsert_profile(visitor, person_data)

        # ── Step 2: Cascade — Proxycurl (linkedin_url → details) ──
        linkedin_url = person_data.get("linkedin_url") or (profile.linkedin_url if profile else None)
        if linkedin_url:
            proxycurl_key = self._get_system_proxycurl_key()
            if proxycurl_key:
                proxycurl_data = await self._enrich_proxycurl(linkedin_url, api_key=proxycurl_key, visitor=visitor)
                if proxycurl_data:
                    _apply_proxycurl(profile, proxycurl_data)
                    logger.info("cascade_proxycurl_ok", visitor_id=visitor.visitor_id[:8])

        # ── Step 3: Cascade — Twitter (handle → bio/followers) ──
        # Runs when EITHER the official X bearer token OR the TwitterAPI.io
        # fallback key is configured — _enrich_twitter picks the provider.
        twitter_handle = person_data.get("twitter_handle") or (profile.twitter_handle if profile else None)
        if twitter_handle:
            twitter_key = self._get_system_twitter_key()
            if twitter_key or settings.twitterapi_io_api_key:
                twitter_data = await self._enrich_twitter(twitter_handle, api_key=twitter_key, visitor=visitor)
                if twitter_data:
                    _apply_twitter(profile, twitter_data)
                    logger.info("cascade_twitter_ok", visitor_id=visitor.visitor_id[:8])

        # ── Step 4 (opt-in): read known YouTube/Reddit content into persona ──
        # Non-fatal, flag-gated, high-intent only. Writes to social_context.
        await self._fetch_and_store_content(visitor, profile, person_data)

        # ── Step 4b (opt-in): read the visitor's PUBLIC GitHub profile ──
        # Non-fatal, flag-gated, only when github_url is already known.
        await self._fetch_and_store_github(visitor, profile)

        # ── Avatar (secondary): if Twitter gave no image, try OSINT profiles.
        # Read after Step 4 so any freshly-written social_context is included.
        if not profile.avatar_url:
            osint_avatar = _avatar_from_social_context(profile.social_context)
            if osint_avatar:
                profile.avatar_url = osint_avatar

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
                profile.linkedin_url, api_key=keys["proxycurl"], visitor=visitor
            )
            if proxycurl_data:
                _apply_proxycurl(profile, proxycurl_data)
                updated = True

        # Twitter (fill if cascade didn't run or returned nothing)
        if "twitter" in keys and profile.twitter_handle and not profile.twitter_bio:
            twitter_data = await self._enrich_twitter(
                profile.twitter_handle, api_key=keys["twitter"], visitor=visitor
            )
            if twitter_data:
                _apply_twitter(profile, twitter_data)
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

    async def _log_enrich(
        self, visitor: Visitor | None, provider: str, operation: str, success: bool
    ) -> None:
        """Record one billable enrichment API call into the cost ledger.

        Only called on a cache MISS (a real HTTP request → real cost). Uses its
        own session (no db passed) so it commits independently of the cascade's
        commit timing — tier2, for one, only commits when something changed.
        Best-effort; never raises.
        """
        if visitor is None:
            return
        await log_api_call(
            site_id=visitor.site_id,
            visitor_id=visitor.visitor_id,
            provider=provider,
            category="enrichment",
            operation=operation,
            success=success,
        )

    @_http_retry
    async def _enrich_pdl(self, email: str, *, visitor: Visitor | None = None) -> dict | None:
        """Enrich a person record from PDL by email.

        Cached in Redis for 7 days (positive and negative results) — the
        enrich_tier1 caller guards the missing-key case.
        Retries up to 3× on transient errors (5xx, 429, timeouts).
        """
        cache_key = f"enrich:pdl:{hashlib.sha256(email.strip().lower().encode()).hexdigest()}"
        hit, cached = await self._cache_get(cache_key)
        if hit:
            logger.debug("pdl_enrich_cache_hit", match=cached is not None)
            return cached

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                "https://api.peopledatalabs.com/v5/person/enrich",
                headers={"X-Api-Key": settings.people_data_labs_api_key},
                params={"email": email},
            )
            if resp.status_code == 200:
                p = resp.json().get("data", {})
                data = {
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
                await self._cache_set(cache_key, data)
                await self._log_enrich(visitor, "pdl", "person_enrich", True)
                return data
            elif resp.status_code == 404:
                logger.debug("pdl_enrich_no_match", email_prefix=email[:5])
                await self._cache_set(cache_key, None)
                await self._log_enrich(visitor, "pdl", "person_enrich", False)
                return None
            else:
                logger.warning("pdl_enrich_error", status=resp.status_code)
                if resp.status_code in _TRANSIENT_HTTP_STATUSES:
                    resp.raise_for_status()
                # Non-transient (401 bad key / 403 / 400): NOT a no-match. Don't
                # negative-cache; signal the caller to keep the visitor retryable.
                raise _PDLNonTransientError(f"PDL non-transient {resp.status_code}")
        return None

    @_http_retry
    async def _enrich_apollo(self, email: str, *, visitor: Visitor | None = None) -> dict | None:
        """Enrich a person from Apollo by email — the fallback when PDL 404s.

        Apollo's coverage skews differently from PDL's (better on non-US and
        small companies), which is the entire reason this exists. Costs 0
        credits when Apollo finds nothing, ~1 when it does; personal emails and
        phone numbers are deliberately NOT requested (``reveal_personal_emails``
        defaults false) — we already hold the address, and revealing more PII
        than the product needs is not free, legally or in credits.

        Returns the same dict shape as ``_enrich_pdl`` so ``_upsert_profile``
        consumes either interchangeably. Cached 7 days, positive and negative.
        """
        if not settings.apollo_api_key or not settings.apollo_enabled:
            return None

        cache_key = f"enrich:apollo:{hashlib.sha256(email.strip().lower().encode()).hexdigest()}"
        hit, cached = await self._cache_get(cache_key)
        if hit:
            logger.debug("apollo_enrich_cache_hit", match=cached is not None)
            return cached

        if settings.mock_external_apis:
            domain = email.rsplit("@", 1)[-1]
            data = {
                "job_title": "Mock Title",
                "company_name": f"Mock Co ({domain})",
                "company_domain": domain,
                "seniority_level": "manager",
            }
            await self._cache_set(cache_key, data)
            return data

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                "https://api.apollo.io/api/v1/people/match",
                headers={"X-Api-Key": settings.apollo_api_key},
                json={"email": email},
            )
            if resp.status_code != 200:
                if resp.status_code == 404:
                    logger.debug("apollo_enrich_no_match", email_prefix=email[:5])
                    await self._cache_set(cache_key, None)
                    await self._log_enrich(visitor, "apollo", "person_enrich", False)
                    return None
                logger.warning("apollo_enrich_error", status=resp.status_code)
                if resp.status_code in _TRANSIENT_HTTP_STATUSES:
                    resp.raise_for_status()
                # Non-transient (401 bad key / 422): not a no-match. Don't
                # negative-cache, and don't raise — PDL already missed, so the
                # caller should still fall through to the free domain fill.
                return None

            person = (resp.json() or {}).get("person") or {}
            if not person:
                # A 200 with no person IS Apollo's documented "no records
                # enriched" answer, so treat it as a definitive miss.
                logger.debug("apollo_enrich_empty_person", email_prefix=email[:5])
                await self._cache_set(cache_key, None)
                await self._log_enrich(visitor, "apollo", "person_enrich", False)
                return None

            org = person.get("organization") or {}
            data = {
                "full_name": person.get("name"),
                "job_title": person.get("title"),
                "company_name": org.get("name"),
                "company_domain": org.get("primary_domain") or org.get("website_url"),
                "company_size": org.get("estimated_num_employees"),
                "industry": org.get("industry"),
                "seniority_level": person.get("seniority"),
                "linkedin_url": person.get("linkedin_url"),
                "twitter_handle": (person.get("twitter_url", "") or "").rstrip("/").split("/")[-1] or None,
                "facebook_url": person.get("facebook_url"),
                "github_url": person.get("github_url"),
                "city": person.get("city"),
                "country": person.get("country"),
            }
            if not any(data.get(f) for f in ("job_title", "company_name", "linkedin_url")):
                # Shape drift guard: a 200 that maps to nothing usable means the
                # response keys moved. Log the keys (never the values — this is
                # PII) so it surfaces instead of silently enriching nobody.
                logger.warning(
                    "apollo_enrich_unmapped_response",
                    person_keys=sorted(person.keys())[:25],
                    org_keys=sorted(org.keys())[:25],
                )
                await self._log_enrich(visitor, "apollo", "person_enrich", False)
                return None

            # company_size arrives as an int; the column is a string.
            if data["company_size"] is not None:
                data["company_size"] = str(data["company_size"])
            await self._cache_set(cache_key, data)
            await self._log_enrich(visitor, "apollo", "person_enrich", True)
            logger.info("cascade_apollo_ok", email_prefix=email[:5])
            return data

    async def _enrich_proxycurl(
        self, linkedin_url: str, *, api_key: str, visitor: Visitor | None = None
    ) -> dict:
        cache_key = f"enrich:proxycurl:{hashlib.sha256(linkedin_url.strip().lower().encode()).hexdigest()}"
        hit, cached = await self._cache_get(cache_key)
        if hit:
            return cached or {}
        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                resp = await client.get(
                    "https://nubela.co/proxycurl/api/v2/linkedin",
                    headers={"Authorization": f"Bearer {api_key}"},
                    params={"url": linkedin_url},
                )
                if resp.status_code == 200:
                    p = resp.json()
                    data = {
                        "linkedin_headline": p.get("headline"),
                        "linkedin_summary": p.get("summary"),
                        "linkedin_follower_count": p.get("follower_count"),
                    }
                    await self._cache_set(cache_key, data)
                    await self._log_enrich(visitor, "proxycurl", "linkedin", True)
                    return data
                if resp.status_code == 404:
                    await self._cache_set(cache_key, None)
                await self._log_enrich(visitor, "proxycurl", "linkedin", resp.status_code == 200)
            except httpx.HTTPError as e:
                logger.error("proxycurl_error", error=str(e))
        return {}

    async def _enrich_twitter(
        self, handle: str, *, api_key: str | None = None, visitor: Visitor | None = None
    ) -> dict:
        """Fetch a Twitter/X user's bio + follower count.

        PRIMARY: official X API v2 (when ``api_key`` bearer token is present).
        FALLBACK: TwitterAPI.io (~50× cheaper) when the official call errors,
        returns a non-200 other than a definitive 404, or no bearer token is
        configured. Gated on ``settings.twitterapi_io_api_key`` (skip if empty).
        Cached (positive + definitive-miss); honors ``mock_external_apis``.
        """
        cache_key = f"enrich:twitter:{handle.strip().lower().lstrip('@')}"
        hit, cached = await self._cache_get(cache_key)
        if hit:
            return cached or {}

        if settings.mock_external_apis:
            data = {
                "twitter_bio": f"Mock bio for @{handle.lstrip('@')}",
                "twitter_follower_count": 1234,
                "avatar_url": "https://pbs.twimg.com/profile_images/000/mock_400x400.jpg",
            }
            await self._cache_set(cache_key, data)
            return data

        handle_clean = handle.strip().lstrip("@")

        # ── PRIMARY: official X API v2 ──
        if api_key:
            async with httpx.AsyncClient(timeout=10.0) as client:
                try:
                    resp = await client.get(
                        f"https://api.twitter.com/2/users/by/username/{handle_clean}",
                        headers={"Authorization": f"Bearer {api_key}"},
                        params={"user.fields": "description,public_metrics,profile_image_url"},
                    )
                    if resp.status_code == 200:
                        u = resp.json().get("data", {})
                        data = {
                            "twitter_bio": u.get("description"),
                            "twitter_follower_count": u.get("public_metrics", {}).get("followers_count"),
                            "avatar_url": _upgrade_twitter_avatar(u.get("profile_image_url")),
                        }
                        await self._cache_set(cache_key, data)
                        await self._log_enrich(visitor, "twitter", "user_lookup", True)
                        return data
                    if resp.status_code == 404:
                        # Definitive no-match — the handle doesn't exist. Don't
                        # waste a fallback call; negative-cache and return.
                        await self._cache_set(cache_key, None)
                        await self._log_enrich(visitor, "twitter", "user_lookup", False)
                        return {}
                    # Any other non-200 (401 bad/expired token, 403, 429, 5xx):
                    # fall through to the TwitterAPI.io fallback below.
                    logger.warning("twitter_official_non200", status=resp.status_code)
                except httpx.HTTPError as e:
                    logger.warning("twitter_official_error", error=str(e))

        # ── FALLBACK: TwitterAPI.io ──
        if not settings.twitterapi_io_api_key:
            # Official path was tried and failed (non-200/error) with no fallback
            # configured — record the failed lookup in the cost ledger for parity
            # with pre-rewrite behavior (observability, not functional).
            if api_key:
                await self._log_enrich(visitor, "twitter", "user_lookup", False)
            return {}
        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                resp = await client.get(
                    "https://api.twitterapi.io/twitter/user/info",
                    headers={"X-API-Key": settings.twitterapi_io_api_key},
                    params={"userName": handle_clean},
                )
                if resp.status_code == 200:
                    payload = resp.json()
                    u = payload.get("data") or {}
                    if payload.get("status") == "error" or not u:
                        # user-not-found / unavailable — definitive miss.
                        await self._cache_set(cache_key, None)
                        await self._log_enrich(visitor, "twitterapi_io", "user_lookup", False)
                        return {}
                    data = {
                        "twitter_bio": u.get("description"),
                        "twitter_follower_count": u.get("followers"),
                        "avatar_url": _upgrade_twitter_avatar(
                            u.get("profilePicture") or u.get("profile_image_url")
                        ),
                    }
                    await self._cache_set(cache_key, data)
                    await self._log_enrich(visitor, "twitterapi_io", "user_lookup", True)
                    return data
                if resp.status_code == 404:
                    await self._cache_set(cache_key, None)
                await self._log_enrich(visitor, "twitterapi_io", "user_lookup", False)
            except httpx.HTTPError as e:
                logger.warning("twitterapi_io_error", error=str(e))
        return {}

    # ──────────────── Content reader (YouTube/Reddit → persona) ───────────

    async def _fetch_and_store_content(
        self, visitor: Visitor, profile: EnrichmentProfile, pdl_data: dict
    ) -> None:
        """Read known YouTube/Reddit content into ``profile.social_context``.

        Flag-gated (``enable_content_reader``), high-intent only (>= 60, matching
        social_intelligence). Runs only when a handle is already known — never
        guesses. Non-fatal: any error is logged and swallowed so a content
        hiccup can't break the enrichment cascade.
        """
        if not settings.enable_content_reader:
            return
        # Match the social-intelligence intent gate (SOCIAL_CONTEXT_MIN_INTENT).
        if (visitor.intent_score or 0) < 60:
            return

        try:
            from apps.api.services.content_reader import (
                extract_content_handles,
                fetch_content_for_handles,
                find_company_channels,
            )

            handles = extract_content_handles(pdl_data, profile.social_context)
            fetched: dict = {}
            if handles:
                fetched = await fetch_content_for_handles(handles)

            # P4 fallback: no PERSONAL handle → try the company's own channels
            # (subreddit / YouTube), confidence-gated on domain. Stored under
            # `company_content` so it's distinguishable from a personal handle.
            if not fetched:
                company_name = pdl_data.get("company_name")
                company_domain = pdl_data.get("company_domain")
                if company_name and company_domain:
                    company_handles = await find_company_channels(company_name, company_domain)
                    if company_handles:
                        company_content = await fetch_content_for_handles(company_handles)
                        if company_content:
                            fetched = {"company_content": company_content}

            if not fetched:
                return

            now = datetime.now(timezone.utc)
            # Read-modify-write: preserve osint_scan / social_resolution /
            # deep_research sub-keys already on social_context.
            merged = dict(profile.social_context or {})
            merged.update(fetched)
            profile.social_context = merged
            profile.social_context_updated_at = now

            logger.info(
                "content_reader_stored",
                visitor_id=visitor.visitor_id[:8],
                sources=list(fetched.keys()),
            )
        except Exception as exc:
            logger.warning(
                "content_reader_enrich_failed",
                visitor_id=visitor.visitor_id[:8],
                error=str(exc)[:200],
            )

    # ──────────────── GitHub public-profile reader (→ persona) ────────────

    async def _fetch_and_store_github(
        self, visitor: Visitor, profile: EnrichmentProfile
    ) -> None:
        """Read the visitor's PUBLIC GitHub profile into ``profile.social_context``.

        Flag-gated (``enable_github_reader``, default OFF), and only when
        ``profile.github_url`` is already known — never guesses a login.
        Non-fatal: any error is logged and swallowed so a GitHub hiccup can't
        break the enrichment cascade.

        Known limitation (pre-existing, out of scope here): a downstream
        Celery-beat sweep (``apps/api/tasks/resolution_tasks.py``) can still
        wholesale-overwrite ``social_context`` via
        ``SocialIntelligence.store_social_context()`` for the same visitor in the
        same pass, destroying the ``github`` key written below along with the
        pre-existing ``osint_scan``/``deep_research``/``youtube``/``reddit``
        sub-keys. This plan documents that behavior rather than fixing it —
        converting ``store_social_context`` to a read-modify-write merge has its
        own blast radius (auto-draft generation reads the overwritten value) and
        deserves its own plan. Tracked in
        ``process/features/visitors-identity/backlog/social-context-wholesale-overwrite-bug_NOTE_07-08-26.md``.
        """
        if not settings.enable_github_reader:
            return
        github_url = getattr(profile, "github_url", None)
        if not github_url:
            return

        try:
            from apps.api.services.github_reader import fetch_github_profile

            data = await fetch_github_profile(github_url)
            if not data:
                return

            # Read-modify-write: preserve osint_scan / social_resolution /
            # deep_research / youtube / reddit sub-keys already on social_context.
            merged = dict(profile.social_context or {})
            merged["github"] = data
            profile.social_context = merged
            profile.social_context_updated_at = datetime.now(timezone.utc)

            logger.info(
                "github_reader_stored",
                visitor_id=visitor.visitor_id[:8],
                repos=len(data.get("top_repos") or []),
            )
        except Exception as exc:
            logger.warning(
                "github_reader_enrich_failed",
                visitor_id=visitor.visitor_id[:8],
                error=str(exc)[:200],
            )

    # ──────────────── Deep Research (Claude API + web search) ─────────────

    @staticmethod
    def _format_osint_seed(seed: dict | None) -> str:
        """Turn OSINT findings into a grounding seed block for the prompt.

        Accepts either a raw social_context blob (with osint_scan /
        social_resolution sub-keys) or a flat {accounts, profiles} dict.
        Returns "" when there is nothing useful to seed.
        """
        if not isinstance(seed, dict):
            return ""
        accounts: list = []
        for key in ("osint_scan", "social_resolution"):
            sub = seed.get(key)
            if isinstance(sub, dict):
                accounts += sub.get("accounts") or []
                accounts += sub.get("profiles") or []
        accounts += seed.get("accounts") or []
        accounts += seed.get("profiles") or []
        if not accounts:
            return ""

        profiles: list[str] = []
        registered: list[str] = []
        seen: set = set()
        for a in accounts:
            if not isinstance(a, dict):
                continue
            site = a.get("site_name") or a.get("platform") or ""
            url = a.get("url")
            uname = (a.get("extra") or {}).get("username") or a.get("handle")
            dedup = (site.lower(), (url or "").lower())
            if not site or dedup in seen:
                continue
            seen.add(dedup)
            if a.get("kind") == "profile" or url:
                label = site
                if uname:
                    label += f" (@{uname})"
                if url:
                    label += f" — {url}"
                profiles.append(label)
            else:
                registered.append(site)

        lines: list[str] = []
        if profiles:
            lines.append("Likely/known profiles (verify and expand — do NOT contradict these):")
            lines += [f"- {p}" for p in profiles[:40]]
        if registered:
            lines.append(
                "Email is also registered on (try to find the handles): "
                + ", ".join(sorted(set(registered))[:40])
            )
        if not lines:
            return ""
        return (
            "\n# Verified accounts found via OSINT (use as starting points):\n"
            + "\n".join(lines)
            + "\n"
        )

    async def deep_research(
        self,
        visitor: Visitor,
        identified: IdentifiedVisitor,
        profile: EnrichmentProfile | None = None,
        osint_seed: dict | None = None,
    ) -> dict:
        """Use Gemini + web search to research a visitor's social-media presence.

        When `osint_seed` (or an earlier OSINT scan written to social_context) is
        present, it is injected into the grounded prompt as verified starting
        points so the model resolves real handles instead of guessing blind.

        Returns {"status": ..., "social_context": ..., "message": ...}.
        Stores results in EnrichmentProfile.social_context (read-modify-write —
        preserves osint_scan / social_resolution sub-keys).
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

        seed_block = self._format_osint_seed(
            osint_seed if osint_seed is not None
            else (profile.social_context if profile else None)
        )

        prompt = f"""Deep-dive research about this person's online presence and social media activity.

{person_context}
{seed_block}
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

OUTPUT FORMAT — keep it SHORT (max ~200 words total):
- Use tight bullet points, not paragraphs.
- No preamble, no filler, no wrap-up section.
- Cover only: main profiles (with handles/links), where they are MOST active, what they post about, one line on professional background, and a 1-2 sentence honest read.
- Direct, conversational tone — not corporate. Write in English."""

        if not settings.gemini_api_key:
            logger.warning("deep_research_skipped_no_api_key")
            return {
                "status": "error",
                "message": "Gemini API key not configured. Set GEMINI_API_KEY to enable deep research.",
            }

        try:
            research_text = await gemini_generate(
                prompt, grounding=True, max_output_tokens=2048
            )
        except GeminiError as e:
            logger.error("deep_research_api_error", error=str(e), visitor_id=visitor.visitor_id[:8])
            return {
                "status": "error",
                "message": f"Gemini API error: {e}",
            }

        if not research_text.strip():
            logger.warning("deep_research_empty_response", visitor_id=visitor.visitor_id[:8])
            return {
                "status": "partial",
                "message": "Deep research returned no results.",
            }
        research_text = research_text.strip()

        if not profile:
            profile = EnrichmentProfile(
                visitor_id=visitor.visitor_id,
                site_id=visitor.site_id,
                enrichment_completeness=0.0,
            )
            self.db.add(profile)

        now = datetime.now(timezone.utc)
        # Read-modify-write: keep osint_scan / social_resolution sub-keys intact.
        merged = dict(profile.social_context or {})
        merged.update({
            "deep_research": research_text,
            "researched_at": now.isoformat(),
            "model": settings.gemini_model,
        })
        profile.social_context = merged
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

    # ──────────────────────── Legacy compat ──────────────────────────────

    async def enrich(self, visitor: Visitor, identified: IdentifiedVisitor) -> EnrichmentProfile | None:
        """Legacy method — calls tier1 only. Used by resolution_tasks.py."""
        return await self.enrich_tier1(visitor, identified)
