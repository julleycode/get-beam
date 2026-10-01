"""Agent-paid operations (agentic commerce) — service layer.

Four operations sold to external AI agents that pay via MPP/x402. Payment is
verified upstream by the apps/web route handler; these functions only do the
work. The router (``routers/agent_paid_internal.py``) maps the exceptions below
to HTTP: ``NoMatch`` → 404 ``{"error": "no_match"}`` (the web handler skips
settlement on it), ``UpstreamError`` → 502, ``PrivacyGateUnavailable`` → 503.

Invariants:
- No tenant: never touches per-site budgets, plan quotas, or the demo budget.
- Privacy gate is never mocked: an email on the suppression list (any scope) or
  tied to a ``do_not_resolve`` visitor via blind index is indistinguishable
  from no match. A gate failure fails CLOSED (503), never open.
- Outputs are professional/public fields only (see ``schemas/agent_paid.py``).
- Every caller-supplied string entering an LLM prompt passes through
  ``agents/prompt_safety`` (``clean_text`` / ``strip_url`` / ``wrap_untrusted``).
- Mock mode (``settings.mock_external_apis``) returns deterministic fakes
  without calling any provider or LLM.
- Logs carry keys/ids only — never emails, names, IPs, prompts, or outputs.
"""

import ipaddress
import json
import re
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

import structlog
from sqlalchemy import and_, exists, or_, select

from apps.api.agents.prompt_safety import clean_text, strip_url, wrap_untrusted
from apps.api.config import settings
from apps.api.models.database import async_session
from apps.api.models.suppression import SuppressionEntry
from apps.api.models.visitor import IdentifiedVisitor, Visitor
from apps.api.models.visitor_email import VisitorEmail
from apps.api.services.pii_crypto import email_hash, normalize_email

logger = structlog.get_logger()


class NoMatch(Exception):
    """Definitive no-match (or privacy-blocked — deliberately the same)."""


class UpstreamError(Exception):
    """A provider/LLM failed to answer — not a verdict."""


class PrivacyGateUnavailable(Exception):
    """The suppression / do_not_resolve check could not run. Fail closed."""


class InvalidIp(ValueError):
    """Syntactically invalid or non-public IP address."""


_MOCK_NO_MATCH_PREFIX = "nomatch"


def _is_mock_no_match(value: str) -> bool:
    """Mock-mode hook so the web handler can exercise its no-settlement path."""
    return value.strip().lower().startswith(_MOCK_NO_MATCH_PREFIX)


# ─── Privacy gate ────────────────────────────────────────────────────────


async def is_email_blocked(email: str) -> bool:
    """True if Beam must not sell data about this email.

    Blocked when the blind index matches (a) ANY suppression-list scope, or
    (b) a ``do_not_resolve`` visitor via ``identified_visitors.email_bidx`` or
    ``visitor_emails.email_bidx``. One round trip; raises
    ``PrivacyGateUnavailable`` on any failure (fail closed).
    """
    try:
        h = email_hash(email)
        suppressed = exists(select(SuppressionEntry.id).where(SuppressionEntry.email_hash == h))
        dnr_identified = exists(
            select(Visitor.id)
            .join(
                IdentifiedVisitor,
                and_(
                    IdentifiedVisitor.site_id == Visitor.site_id,
                    IdentifiedVisitor.visitor_id == Visitor.visitor_id,
                ),
            )
            .where(IdentifiedVisitor.email_bidx == h, Visitor.do_not_resolve.is_(True))
        )
        dnr_captured = exists(
            select(Visitor.id)
            .join(
                VisitorEmail,
                and_(
                    VisitorEmail.site_id == Visitor.site_id,
                    VisitorEmail.visitor_id == Visitor.visitor_id,
                ),
            )
            .where(VisitorEmail.email_bidx == h, Visitor.do_not_resolve.is_(True))
        )
        async with async_session() as db:
            result = await db.execute(select(or_(suppressed, dnr_identified, dnr_captured)))
            return bool(result.scalar())
    except Exception as exc:
        logger.warning("agent_paid_privacy_gate_failed", error_type=type(exc).__name__)
        raise PrivacyGateUnavailable() from exc


async def _require_not_blocked(email: str) -> None:
    if await is_email_blocked(email):
        raise NoMatch()


# ─── 1. enrich-email ─────────────────────────────────────────────────────

_PERSON_FIELDS = ("full_name", "job_title", "linkedin_url")


def _project_professional(data: dict[str, Any]) -> dict[str, Any]:
    """Whitelist projection: provider dict → professional fields only."""
    location = {
        "city": data.get("city"),
        "region": data.get("region") or data.get("state"),
        "country": data.get("country"),
    }
    return {
        "full_name": data.get("full_name"),
        "job_title": data.get("job_title"),
        "company_name": data.get("company_name"),
        "company_domain": data.get("company_domain"),
        "linkedin_url": data.get("linkedin_url"),
        "location": location if any(location.values()) else None,
    }


async def enrich_email(email: str) -> tuple[dict[str, Any], str]:
    """PDL → Apollo person enrichment. Returns (professional_fields, provider)."""
    email = normalize_email(email)
    await _require_not_blocked(email)

    if settings.mock_external_apis:
        if _is_mock_no_match(email):
            raise NoMatch()
        domain = email.rsplit("@", 1)[-1]
        return (
            {
                "full_name": "Mock Person",
                "job_title": "Mock Title",
                "company_name": f"Mock Co ({domain})",
                "company_domain": domain,
                "linkedin_url": "https://www.linkedin.com/in/mock-person",
                "location": {"city": "Mock City", "region": None, "country": "US"},
            },
            "mock",
        )

    from apps.api.services.enricher import Enricher

    # db-less, exactly like /demo/identify-by-email (visitor=None → no ledger rows).
    enricher = Enricher(None)  # type: ignore[arg-type]
    errors = 0
    attempted = 0

    if settings.people_data_labs_api_key:
        attempted += 1
        try:
            data = await enricher._enrich_pdl(email)
        except Exception as exc:  # transient-after-retries or non-transient key error
            errors += 1
            data = None
            logger.warning("agent_paid_provider_error", provider="pdl", error_type=type(exc).__name__)
        if data and any(data.get(f) for f in _PERSON_FIELDS):
            return _project_professional(data), "pdl"

    if settings.apollo_api_key and settings.apollo_enabled:
        attempted += 1
        try:
            data = await enricher._enrich_apollo(email)
        except Exception as exc:
            errors += 1
            data = None
            logger.warning("agent_paid_provider_error", provider="apollo", error_type=type(exc).__name__)
        if data and any(data.get(f) for f in _PERSON_FIELDS):
            return _project_professional(data), "apollo"

    # Nothing configured, or every provider errored: no verdict → 502, so the
    # caller is not charged for an answer Beam never got.
    if attempted == 0 or errors == attempted:
        raise UpstreamError()
    raise NoMatch()


# ─── 2. ip-company ───────────────────────────────────────────────────────


def validate_public_ip(raw: str) -> str:
    """Return the canonical form of a public IP, or raise ``InvalidIp``."""
    try:
        ip = ipaddress.ip_address(raw.strip())
    except ValueError as exc:
        raise InvalidIp("invalid_ip") from exc
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    if (
        ip.is_private
        or ip.is_loopback
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_link_local
        or ip.is_unspecified
        or not ip.is_global
    ):
        raise InvalidIp("non_public_ip")
    return str(ip)


def _company_name_from_domain(domain: str) -> str | None:
    """'acme-corp.co.uk' → 'Acme Corp' (derived label; providers here give domains)."""
    label = domain.strip().lower().removeprefix("www.").split(".")[0]
    name = label.replace("-", " ").replace("_", " ").strip().title()
    return name or None


def _clean_domain(value: str | None) -> str | None:
    if not value:
        return None
    d = value.strip().lower()
    d = re.sub(r"^https?://", "", d).split("/")[0].removeprefix("www.")
    return d if "." in d else None


# (source, confidence) — mirrors company_graph's rDNS 0.5 / paid 0.7 ladder;
# ipinfo sits between because its free-tier domain is an org-name heuristic.
_RUNG_RDNS = ("rdns", 0.5)
_RUNG_PDL = ("pdl_ip", 0.7)
_RUNG_IPINFO = ("ipinfo", 0.6)


async def ip_company(raw_ip: str) -> dict[str, Any]:
    """IP → company via the existing ladder (rDNS cache → PDL IP → IPinfo)."""
    ip = validate_public_ip(raw_ip)

    if settings.mock_external_apis:
        return {
            "company_name": "Mock Corp",
            "domain": "mockcorp.example",
            "confidence": 0.5,
            "source": "mock",
        }

    from apps.api.services.company_resolver import resolve_company_cached
    from apps.api.services.identity_resolver import IdentityResolver

    # db-less stub visitor, exactly like /demo/identify.
    resolver = IdentityResolver(db=None)  # type: ignore[arg-type]
    stub = SimpleNamespace(
        ip_address=ip, country_code=None, visitor_id="agent_paid", site_id="agent_paid",
        company_domain=None, pages_visited=[],
    )

    async def _rdns() -> str | None:
        return await resolve_company_cached(ip)

    rungs: list[tuple[tuple[str, float], Any]] = [(_RUNG_RDNS, _rdns)]
    if settings.people_data_labs_api_key:
        rungs.append((_RUNG_PDL, lambda: resolver._call_pdl_ip_enrich(stub)))  # type: ignore[arg-type]
    if settings.ipinfo_token:
        rungs.append((_RUNG_IPINFO, lambda: resolver._call_ipinfo_api(stub)))  # type: ignore[arg-type]

    paid_attempted = len(rungs) - 1
    errors = 0
    for (source, confidence), call in rungs:
        try:
            domain = _clean_domain(await call())
        except Exception as exc:
            errors += 1
            logger.warning("agent_paid_provider_error", provider=source, error_type=type(exc).__name__)
            continue
        if domain:
            return {
                "company_name": _company_name_from_domain(domain),
                "domain": domain,
                "confidence": confidence,
                "source": source,
            }

    # rDNS never raises, so a miss there is a verdict only when no paid rung
    # exists. If every configured paid rung failed (rather than missed), Beam
    # has no answer worth billing → 502.
    if paid_attempted and errors >= paid_attempted:
        raise UpstreamError()
    raise NoMatch()


# ─── 3. deep-research ────────────────────────────────────────────────────

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_PHONE_INTL_RE = re.compile(r"\+\d[\d\s().-]{7,}\d")
_PHONE_NANP_RE = re.compile(r"\(?\b\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}\b")


def redact_contact_details(text: str) -> str:
    """Best-effort removal of email addresses and phone numbers from LLM output."""
    text = _EMAIL_RE.sub("[redacted]", text)
    text = _PHONE_INTL_RE.sub("[redacted]", text)
    return _PHONE_NANP_RE.sub("[redacted]", text)


_PAID_RESEARCH_RULES = (
    "\nADDITIONAL RULES:\n"
    "- Report only professional or publicly published information.\n"
    "- Never include email addresses, phone numbers, home addresses, or family details.\n"
)


def build_paid_research_prompt(
    full_name: str,
    company_name: str | None,
    job_title: str | None,
    linkedin_url: str | None,
    email: str | None,
) -> str:
    """Sanitize every caller value and fence it before the shared research prompt."""
    person: dict[str, Any] = {"Name": clean_text(full_name, 80)}
    if email:
        person["Email"] = clean_text(email, 254)
    if linkedin_url:
        person["LinkedIn"] = strip_url(linkedin_url)
    if company_name:
        person["Company"] = clean_text(company_name, 120)
    if job_title:
        person["Title"] = clean_text(job_title, 120)

    from apps.api.services.enricher import build_deep_research_prompt

    fenced = wrap_untrusted(json.dumps(person, ensure_ascii=False))
    return build_deep_research_prompt(fenced, _PAID_RESEARCH_RULES)


async def deep_research(
    full_name: str,
    company_name: str | None = None,
    job_title: str | None = None,
    linkedin_url: str | None = None,
    email: str | None = None,
) -> dict[str, Any]:
    """Gemini grounded research using the visitor path's prompt. Returns response fields."""
    if email:
        email = normalize_email(email)
        await _require_not_blocked(email)

    prompt = build_paid_research_prompt(full_name, company_name, job_title, linkedin_url, email)
    now = datetime.now(timezone.utc).isoformat()

    if settings.mock_external_apis:
        if _is_mock_no_match(full_name):
            raise NoMatch()
        return {
            "summary": "- Mock research summary: public professional profile on LinkedIn.\n"
            "- Posts about B2B SaaS growth.",
            "researched_at": now,
            "model": "mock",
        }

    if not settings.gemini_api_key:
        raise UpstreamError()

    from apps.api.services.enricher import DEEP_RESEARCH_MAX_OUTPUT_TOKENS
    from apps.api.services.gemini_client import gemini_generate

    try:
        text = await gemini_generate(
            prompt, grounding=True, max_output_tokens=DEEP_RESEARCH_MAX_OUTPUT_TOKENS
        )
    except Exception as exc:
        logger.warning("agent_paid_provider_error", provider="gemini", error_type=type(exc).__name__)
        raise UpstreamError() from exc

    text = redact_contact_details((text or "").strip())
    if not text:
        raise NoMatch()
    return {"summary": text, "researched_at": now, "model": settings.gemini_model}


# ─── 4. outreach-draft ───────────────────────────────────────────────────


async def outreach_draft(
    visitor_name: str,
    visitor_role: str | None = None,
    visitor_company: str | None = None,
    user_url: str | None = None,
    recent_post: str | None = None,
) -> dict[str, str]:
    """Shared demo draft logic with sanitized + fenced inputs. LLM-only (no template)."""
    from apps.api.services.outreach_draft import build_draft_prompt, generate_llm_draft

    name = clean_text(visitor_name, 80) or ""
    role = clean_text(visitor_role or "", 120) or ""
    company = clean_text(visitor_company or "", 120) or ""
    site = strip_url(user_url) if user_url else ""
    post = clean_text(recent_post or "", 800) or ""

    prompt = build_draft_prompt(name, role, company, site, post, fence=True)

    if settings.mock_external_apis:
        return {"draft": "loved this take — would be great to swap notes sometime.", "source": "mock"}

    result = await generate_llm_draft(prompt)
    if result is None:
        # The demo's canned template is not a sellable answer.
        raise UpstreamError()
    return {"draft": result.draft, "source": result.source}
