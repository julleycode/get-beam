from html import escape
from urllib.parse import quote

import httpx
import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.config import settings
from apps.api.models.visitor import IdentifiedVisitor
from apps.api.services.link_decorator import generate_unsubscribe_token
from apps.api.services.pii import mask_email as _mask_email

logger = structlog.get_logger()

SENDGRID_API_URL = "https://api.sendgrid.com/v3/mail/send"


class EmailSender:
    async def _is_suppressed(self, db: AsyncSession, to_email: str) -> bool:
        """True if any identified visitor with this email is flagged do_not_email.

        Case-insensitive match: stored emails may be mixed case while input is
        typically lowercased, so compare lower() to lower().
        """
        result = await db.execute(
            select(IdentifiedVisitor.id)
            .where(
                func.lower(IdentifiedVisitor.email) == to_email.strip().lower(),
                IdentifiedVisitor.do_not_email.is_(True),
            )
            .limit(1)
        )
        return result.scalar_one_or_none() is not None

    async def send(
        self,
        to_email: str,
        subject: str,
        body_html: str,
        from_name: str = "Beam",
        from_email: str = "hello@getbeam.fyi",
        unsubscribe_url: str | None = None,
        db: AsyncSession | None = None,
    ) -> dict | None:
        # Suppression check (do_not_email set by unsubscribe + bounce webhook).
        # `db` is optional so purely transactional callers without a session
        # (waitlist invites, admin notifications — recipients who are not
        # visitors) keep working unchanged; any visitor-targeted or campaign
        # send MUST pass a session to get the check. Returns None (falsy) when
        # the send is skipped.
        if db is not None and await self._is_suppressed(db, to_email):
            logger.info("email_suppressed", to=_mask_email(to_email))
            return None

        if not unsubscribe_url:
            token = generate_unsubscribe_token(to_email)
            unsubscribe_url = f"{settings.api_base_url}/unsubscribe?t={quote(token, safe='')}"

        full_html = f"""{body_html}
<br/><br/>
<p style="font-size:12px;color:#999;">
    <a href="{escape(unsubscribe_url, quote=True)}">Unsubscribe</a> from future emails.
</p>"""

        payload = {
            "personalizations": [{"to": [{"email": to_email}]}],
            "from": {"email": from_email, "name": from_name},
            "subject": subject,
            "content": [{"type": "text/html", "value": full_html}],
            "headers": {"List-Unsubscribe": f"<{unsubscribe_url}>"},
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    SENDGRID_API_URL,
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {settings.sendgrid_api_key}",
                        "Content-Type": "application/json",
                    },
                )

            if response.status_code in (200, 201, 202):
                msg_id = response.headers.get("X-Message-Id", "unknown")
                logger.info("email_sent", to=_mask_email(to_email), id=msg_id, status=response.status_code)
                return {"id": msg_id, "status": response.status_code}

            logger.error(
                "email_send_failed",
                to=_mask_email(to_email),
                status=response.status_code,
                body=response.text[:500],
            )
            raise RuntimeError(f"SendGrid {response.status_code}: {response.text[:200]}")

        except httpx.HTTPError as e:
            logger.error("email_send_failed", to=_mask_email(to_email), error=str(e))
            raise
