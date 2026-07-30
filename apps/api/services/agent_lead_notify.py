"""Owner notification for WS3 agent-concierge leads.

Kept OUT of ``agent_gateway.py`` on purpose: that module's builders are guarded
(test_builders_never_read_operational_site_columns) against reading any
operational Site column, and resolving the owner requires ``site.user_id`` ->
``User.email``. This internal notification path is not a public-response builder,
so it lives here where reading ``user_id`` is legitimate.
"""

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.models.site import Site

logger = structlog.get_logger()


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


async def notify_owner_of_lead(db: AsyncSession, site: Site, lead) -> None:
    """Fire the owner-notification email for a new lead.

    The caller (handle_conversion_tool) wraps this in a fail-open try/except and
    has ALREADY committed the lead + returned the JSON-RPC success result, so
    this must never block or 500 the response. All 3 qualification fields are
    already sanitized (Must-Fix 2) — interpolated only after clean_text, never
    the raw JSON-RPC params."""
    from apps.api.services.email_sender import EmailSender

    owner = await _owner_email(db, site)
    if not owner:
        logger.info("agent_lead_notify_skipped_no_owner", site_id=site.site_id)
        return
    use_case = lead.use_case or "—"
    company_size = lead.company_size or "—"
    evaluating_against = lead.evaluating_against or "—"
    company = lead.resolved_company_domain or "unknown"
    body_html = (
        f"<p>A new <strong>{lead.tool_name}</strong> lead came in via your AI "
        f"agent concierge.</p>"
        f"<ul>"
        f"<li><strong>Use case:</strong> {use_case}</li>"
        f"<li><strong>Company size:</strong> {company_size}</li>"
        f"<li><strong>Evaluating against:</strong> {evaluating_against}</li>"
        f"<li><strong>Company (best-effort):</strong> {company}</li>"
        f"</ul>"
    )
    await EmailSender().send(
        to_email=owner,
        subject=f"New {lead.tool_name} lead from your AI agent concierge",
        body_html=body_html,
        db=db,
        branding=False,
        custom_args={"site_id": site.site_id, "lead_id": str(lead.id)},
    )
