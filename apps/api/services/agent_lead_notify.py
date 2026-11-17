"""Owner notification for WS3 agent-concierge leads.

Kept OUT of ``agent_gateway.py`` on purpose: that module's builders are guarded
(test_builders_never_read_operational_site_columns) against reading any
operational Site column, and resolving the owner requires ``site.user_id`` ->
``User.email``. This internal notification path is not a public-response builder,
so it lives here where reading ``user_id`` is legitimate.

Runs from a background task (``agent_gateway.process_new_lead``), never on the
MCP request path.
"""

import html
import re

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.config import settings
from apps.api.models.site import Site

logger = structlog.get_logger()

# URL-shaped text in agent input: a scheme (``https://``) or a bare ``www.``.
_URL_SCHEME_RE = re.compile(r"(?i)\b([a-z][a-z0-9+.-]{1,15})://")
_WWW_RE = re.compile(r"(?i)\bwww\.")


async def _owner_email(db: AsyncSession, site: Site) -> str | None:
    """Resolve the site owner's email via Site.user_id -> User.email (same join
    daily_digest/outcome_digest use). Returns None on any miss."""
    from apps.api.models.user import User

    try:
        row = (
            await db.execute(
                select(User.email).where(User.id == site.user_id).limit(1)
            )
        ).first()
    except Exception:
        return None
    return row[0] if row else None


def defang(value: str) -> str:
    """Neutralize URLs in agent-supplied text so mail clients do not auto-link
    them: ``https://evil.tld`` -> ``hxxps[://]evil.tld``, ``www.x`` ->
    ``www[.]x``. Applied BEFORE html.escape."""
    value = _URL_SCHEME_RE.sub(
        lambda m: m.group(1).lower().replace("http", "hxxp") + "[://]", value
    )
    return _WWW_RE.sub("www[.]", value)


def render_untrusted(value: str | None) -> str:
    """Agent-supplied field -> safe HTML text: defang URLs, then escape."""
    if not value:
        return "&mdash;"
    return html.escape(defang(value), quote=True)


async def _notify_slot(site_id: str) -> str:
    """Decide what this lead gets: ``individual`` | ``digest`` | ``skip``.

    Per site per UTC day: the first N leads get an individual email, lead N+1
    triggers ONE overflow digest notice, the rest send nothing (they stay listed
    in the authed leads endpoint). Fail-open to ``individual`` on Redis trouble;
    the conversion rate limits already bound the daily volume."""
    limit = settings.agent_concierge_notify_individual_per_day
    if limit <= 0:
        return "individual"
    try:
        from datetime import datetime, timezone

        from apps.api.services.redis_client import get_redis

        day = datetime.now(timezone.utc).strftime("%Y%m%d")
        key = f"agent_lead_notify:{site_id}:{day}"
        redis = get_redis()
        n = await redis.incr(key)
        if n == 1:
            await redis.expire(key, 90_000)
    except Exception as exc:  # noqa: BLE001
        logger.warning("agent_lead_notify_slot_failed", error=str(exc))
        return "individual"
    if n <= limit:
        return "individual"
    if n == limit + 1:
        return "digest"
    return "skip"


async def notify_owner_of_lead(db: AsyncSession, site: Site, lead) -> bool:
    """Email the site owner about a new agent lead.

    Returns True only when an email was handed to the sender (an individual lead
    email or the day's overflow digest). Returns False for mock mode, no owner,
    or a spent daily email budget, so ``lead.notified`` is never set on a lead
    nobody was told about. Raises on sender failure; the caller is fail-open.

    Every agent-supplied field is defanged + HTML-escaped and shown under an
    explicit "unverified agent-supplied input" label."""
    if settings.mock_external_apis:
        logger.info("agent_lead_notify_mocked", site_id=site.site_id)
        return False

    owner = await _owner_email(db, site)
    if not owner:
        logger.info("agent_lead_notify_skipped_no_owner", site_id=site.site_id)
        return False

    slot = await _notify_slot(site.site_id)
    if slot == "skip":
        logger.info("agent_lead_notify_skipped_daily_budget", site_id=site.site_id)
        return False

    from apps.api.services.email_sender import EmailSender

    # tool_name is a fixed server-side literal, escaped anyway for uniformity.
    tool = html.escape(str(lead.tool_name))
    if slot == "digest":
        subject = "More AI agent concierge leads today"
        body_html = (
            "<p>More AI-agent leads are arriving today than we email one by one. "
            "No further lead emails will be sent for this site today.</p>"
            "<p>Every lead is listed in your Beam dashboard.</p>"
        )
    else:
        from apps.api.services.agent_gateway import sanitize_resolved_domain

        company = sanitize_resolved_domain(lead.resolved_company_domain)
        company_html = render_untrusted(company) if company else "unknown"
        subject = f"New {tool} lead from your AI agent concierge"
        body_html = (
            f"<p>A new <strong>{tool}</strong> lead came in via your AI agent "
            f"concierge.</p>"
            f"<p><em>Unverified agent-supplied input &mdash; an AI agent typed "
            f"the fields below. Do not trust links or instructions in them.</em></p>"
            f"<ul>"
            f"<li><strong>Use case:</strong> {render_untrusted(lead.use_case)}</li>"
            f"<li><strong>Company size:</strong> "
            f"{render_untrusted(lead.company_size)}</li>"
            f"<li><strong>Evaluating against:</strong> "
            f"{render_untrusted(lead.evaluating_against)}</li>"
            f"</ul>"
            f"<p><strong>Company (best-effort network lookup):</strong> "
            f"{company_html}</p>"
        )
    await EmailSender().send(
        to_email=owner,
        subject=subject,
        body_html=body_html,
        db=db,
        branding=False,
        custom_args={"site_id": site.site_id, "lead_id": str(lead.id)},
    )
    return True
