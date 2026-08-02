"""RB2B identity-graph provider mixin."""

from __future__ import annotations

import httpx
import structlog

from apps.api.config import settings
from apps.api.models.visitor import Visitor
from apps.api.services.identity_providers.base import _http_retry

logger = structlog.get_logger()


def _looks_like_plaintext_email(value: object) -> bool:
    """True only for real addresses — RB2B often returns MD5/SHA HEMs here."""
    if not isinstance(value, str):
        return False
    candidate = value.strip()
    if "@" not in candidate or candidate.count("@") != 1:
        return False
    local, _, domain = candidate.partition("@")
    return bool(local) and "." in domain and " " not in candidate


def _first_plaintext_email(*candidates: object) -> str | None:
    for candidate in candidates:
        if isinstance(candidate, list):
            for item in candidate:
                if _looks_like_plaintext_email(item):
                    return str(item).strip()
        elif _looks_like_plaintext_email(candidate):
            return str(candidate).strip()
    return None


def _compose_full_name(person: dict) -> str | None:
    direct = (person.get("full_name") or "").strip()
    if direct:
        return direct
    parts = [
        str(person.get("first_name") or "").strip(),
        str(person.get("last_name") or "").strip(),
    ]
    joined = " ".join(p for p in parts if p)
    return joined or None


def _normalize_score(raw: object) -> float:
    try:
        score = float(raw) if raw is not None else 0.9
    except (TypeError, ValueError):
        score = 0.9
    # RB2B may return 0-1 or 0-100.
    if score > 1:
        score = score / 100.0
    return max(0.0, min(score, 0.99))


_COUNTRY_NAME_TO_ISO = {
    "united states": "US",
    "united states of america": "US",
    "usa": "US",
    "u.s.": "US",
    "u.s.a.": "US",
    "canada": "CA",
    "united kingdom": "GB",
    "great britain": "GB",
}


def _normalize_country(value: object, default: str = "US") -> str:
    """identified_visitors.country is varchar(5) — store ISO, not long names."""
    if value is None:
        return default
    text = str(value).strip()
    if not text:
        return default
    if len(text) <= 5:
        return text.upper() if text.isalpha() else text
    return _COUNTRY_NAME_TO_ISO.get(text.lower(), default)


def parse_rb2b_business_profile(person: dict, hem_score: object = 0.9) -> dict | None:
    """Map an RB2B profile `result` into IdentityResolver data.

    `hem_to_business_profile` often returns MD5s in email fields.
    `identity/business` (Full Business Enrichment) returns plaintext in
    `work_email_confirmed` for the same HEM. Only values that look like
    real addresses are kept; MD5/SHA digests are ignored.
    """
    if not isinstance(person, dict):
        return None

    email = _first_plaintext_email(
        person.get("work_email"),
        person.get("work_email_confirmed"),
        person.get("link_email"),
        person.get("personal_emails"),
    )
    full_name = _compose_full_name(person)
    linkedin_url = person.get("linkedin_url") or person.get("linkedinurl") or None
    if isinstance(linkedin_url, str):
        linkedin_url = linkedin_url.strip() or None

    title = person.get("current_title") or person.get("title") or None
    if isinstance(title, str):
        title = title.strip() or None
    company = person.get("current_company") or person.get("company") or None
    if isinstance(company, str):
        company = company.strip() or None

    if not email and not full_name:
        return None

    return {
        "email": email,
        "full_name": full_name,
        "title": title,
        "company": company,
        "linkedin_url": linkedin_url,
        "city": person.get("city") or None,
        "region": person.get("state") or person.get("region") or None,
        "country": _normalize_country(person.get("country")),
        "confidence_score": _normalize_score(hem_score),
    }


def _merge_rb2b_identity(base: dict | None, extra: dict | None) -> dict | None:
    """Prefer plaintext email / richer fields from the enrichment call."""
    if not base:
        return extra
    if not extra:
        return base
    merged = dict(base)
    if extra.get("email"):
        merged["email"] = extra["email"]
    for key in (
        "full_name",
        "title",
        "company",
        "linkedin_url",
        "city",
        "region",
        "country",
        "confidence_score",
    ):
        if not merged.get(key) and extra.get(key):
            merged[key] = extra[key]
    return merged


class RB2BMixin:
    @_http_retry
    async def _call_rb2b_api(self, visitor: Visitor) -> dict | None:
        """Call RB2B Identification API branch (rb2b_api), not Beam cookie/FP.

        Beam only forwards ip_address (+ optional user_agent). RB2B may use its
        own network graph server-side; this is NOT "identified by IP alone" and
        Beam cookie/fp2_* are never sent. Results are person-level *candidates*
        and are not emailable without a first-party signal.

        Chain (api.rb2b.com/api/v1/):
        1. ip_to_hem
        2. hem_to_business_profile (name / LinkedIn; emails often hashed)
        3. identity/business when step 2 lacks plaintext email (work_email_confirmed)
        """
        rb2b_headers = {
            "Api-Key": settings.rb2b_api_key,
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=15.0) as client:
            # Step 1: IP → Hashed Email Match (HEM)
            resp = await client.post(
                "https://api.rb2b.com/api/v1/ip_to_hem",
                headers=rb2b_headers,
                json={
                    "ip_address": visitor.ip_address,
                    "user_agent": getattr(visitor, "user_agent", "") or "",
                    "include_sha256": True,
                },
            )

            if resp.status_code == 404:
                logger.debug("rb2b_no_match", ip=visitor.ip_address[:8])
                return None
            if resp.status_code == 403:
                logger.warning("rb2b_service_unavailable", detail=resp.text[:200])
                return None
            if resp.status_code != 200:
                logger.warning("rb2b_ip_error", status=resp.status_code,
                               detail=resp.text[:200])
                self._raise_if_transient(resp)
                return None

            hem_data = resp.json()
            results = hem_data.get("results", [])
            if not results:
                logger.debug("rb2b_no_hem", ip=visitor.ip_address[:8])
                return None

            def _raw_score(row: dict) -> float:
                try:
                    return float(row.get("score") or 0)
                except (TypeError, ValueError):
                    return 0.0

            best = max(results, key=_raw_score)
            md5 = best.get("md5")
            hem = md5 or best.get("sha256")
            if not hem:
                logger.debug("rb2b_no_hem_hash", ip=visitor.ip_address[:8])
                return None

            # Step 2: HEM → Business Profile (name/LinkedIn; email often hashed)
            profile_resp = await client.post(
                "https://api.rb2b.com/api/v1/hem_to_business_profile",
                headers=rb2b_headers,
                json={"md5": md5} if md5 else {"sha256": hem},
            )

            parsed: dict | None = None
            if profile_resp.status_code == 200:
                person = profile_resp.json().get("result", profile_resp.json())
                parsed = parse_rb2b_business_profile(person, best.get("score", 0.9))
            elif profile_resp.status_code not in (404, 403):
                logger.warning("rb2b_profile_error", status=profile_resp.status_code)
                self._raise_if_transient(profile_resp)
            else:
                logger.debug(
                    "rb2b_profile_unavailable",
                    status=profile_resp.status_code,
                    ip=visitor.ip_address[:8],
                )

            # Step 3: Full Business Enrichment — plaintext work email when available.
            # Requires md5 (API rejects sha256-only / ip_address).
            if md5 and (not parsed or not parsed.get("email")):
                enrich_resp = await client.post(
                    "https://api.rb2b.com/api/v1/identity/business",
                    headers=rb2b_headers,
                    json={"md5": md5},
                )
                if enrich_resp.status_code == 200:
                    enrich_person = enrich_resp.json().get(
                        "result", enrich_resp.json()
                    )
                    enriched = parse_rb2b_business_profile(
                        enrich_person, best.get("score", 0.9)
                    )
                    parsed = _merge_rb2b_identity(parsed, enriched)
                    if enriched and enriched.get("email"):
                        logger.info(
                            "rb2b_identity_business_email",
                            ip=visitor.ip_address[:8],
                        )
                elif enrich_resp.status_code not in (404, 403, 400):
                    logger.warning(
                        "rb2b_identity_business_error",
                        status=enrich_resp.status_code,
                    )
                    self._raise_if_transient(enrich_resp)

            if not parsed:
                logger.debug(
                    "rb2b_no_identity_in_profile",
                    ip=visitor.ip_address[:8],
                )
                return None
            return parsed
